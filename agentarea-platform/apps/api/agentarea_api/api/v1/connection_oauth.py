"""One-click OAuth for trusted catalog connections.

The public contract deliberately speaks only about connections. Catalog
templates choose the transport internally; users click Connect and authorize.
"""

import json
import logging
import re
import secrets
import time
import urllib.parse
from typing import Any, Literal
from uuid import UUID

import httpx
from agentarea_api.api.deps.services import DatabaseSessionDep, get_real_secret_manager
from agentarea_api.api.v1.registries import require_platform_catalog_write
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.config import get_settings
from agentarea_common.constants import PLATFORM_PRINCIPAL_ID, PLATFORM_WORKSPACE_ID
from agentarea_common.infrastructure.connection_manager import get_connection_manager
from agentarea_mcp.application.auth_service import MCPAuthService, MissingCredentialsError
from agentarea_mcp.application.oauth_client_service import PKCEPair
from agentarea_mcp.infrastructure.auth_repository import MCPAuthConfigRepository
from agentarea_openapi.application.service import OpenAPIConnectionService
from agentarea_openapi.application.url_validator import validate_url
from agentarea_openapi.infrastructure.repository import OpenAPIConnectionRepository
from agentarea_openapi.schemas.dto import OpenAPIConnectionCreate
from agentarea_registry.infrastructure.repository import RegistryItemRepository, RegistryRepository
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connections", tags=["connections"])
public_router = APIRouter(prefix="/connections", tags=["connections"])

_STATE_PREFIX = "connection_oauth_state"
_STATE_TTL_SECONDS = 600
_MANAGED_CREDENTIALS_PREFIX = "connection_oauth_client:"


class CatalogConnectionRequest(BaseModel):
    """Connect with AgentArea credentials, or override them from Advanced."""

    model_config = ConfigDict(extra="forbid")

    credential_mode: Literal["managed", "custom"] = "managed"
    client_id: str | None = Field(default=None, min_length=1, max_length=512)
    client_secret: str | None = Field(default=None, min_length=1, max_length=4096)
    return_to: str = Field(default="", max_length=2048)


class CatalogConnectionResponse(BaseModel):
    connection_id: UUID
    authorize_url: str


class ManagedOAuthAppRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(min_length=1, max_length=512)
    client_secret: str = Field(min_length=1, max_length=4096)


class ManagedOAuthAppResponse(BaseModel):
    provider_key: str
    configured: bool


async def _redis():
    from agentarea_common.events.redis_event_broker import RedisEventBroker

    event_broker = await get_connection_manager().get_event_broker()
    if isinstance(event_broker, RedisEventBroker):
        await event_broker._ensure_connected()
        if event_broker.raw_redis is not None:
            return event_broker.raw_redis
    raise HTTPException(status_code=500, detail="Redis not available")


async def _store_state(state: str, payload: dict[str, Any]) -> None:
    redis = await _redis()
    await redis.set(f"{_STATE_PREFIX}:{state}", json.dumps(payload), ex=_STATE_TTL_SECONDS)


async def _pop_state(state: str) -> dict[str, Any] | None:
    redis = await _redis()
    key = f"{_STATE_PREFIX}:{state}"
    raw = await redis.get(key)
    if raw is None:
        return None
    await redis.delete(key)
    return json.loads(raw)


def _callback_uri() -> str:
    return f"{get_settings().app.API_BASE_URL.rstrip('/')}/v1/connections/oauth/callback"


def _frontend_base(return_to: str) -> str:
    default = get_settings().app.FRONTEND_BASE_URL.rstrip("/")
    requested = urllib.parse.urlparse(return_to)
    expected = urllib.parse.urlparse(default)
    if (
        requested.scheme in {"http", "https"}
        and requested.netloc
        and requested.scheme == expected.scheme
        and requested.netloc == expected.netloc
    ):
        return f"{requested.scheme}://{requested.netloc}"
    return default


def _origin(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Catalog OAuth URLs must use HTTPS")
    return f"{parsed.scheme}://{parsed.netloc}"


def _oauth_profile(spec: dict[str, Any]) -> dict[str, Any]:
    oauth = spec.get("oauth")
    if not isinstance(oauth, dict):
        raise HTTPException(status_code=400, detail="Connection does not support OAuth")

    required = (
        "provider_key",
        "authorization_url",
        "token_url",
        "managed_credentials_key",
    )
    missing = [field for field in required if not oauth.get(field)]
    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"Catalog OAuth template is missing: {', '.join(missing)}",
        )
    managed_key = str(oauth["managed_credentials_key"])
    if not managed_key.startswith(_MANAGED_CREDENTIALS_PREFIX):
        raise HTTPException(status_code=500, detail="Invalid managed OAuth secret key")

    for url_field in ("authorization_url", "token_url"):
        url = str(oauth[url_field])
        _origin(url)
        try:
            validate_url(url, allow_private=False)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="Catalog OAuth URL is not allowed") from exc
    scheme = str(oauth.get("authorization_scheme") or "Bearer")
    if scheme not in {"Bearer", "OAuth"}:
        raise HTTPException(status_code=500, detail="Unsupported authorization scheme")
    method = str(oauth.get("client_auth_method") or "client_secret_post")
    if method not in {"client_secret_post", "client_secret_basic"}:
        raise HTTPException(status_code=500, detail="Unsupported OAuth client auth method")
    scopes = oauth.get("scopes") or []
    if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
        raise HTTPException(status_code=500, detail="Invalid OAuth scopes")
    return {**oauth, "authorization_scheme": scheme, "client_auth_method": method, "scopes": scopes}


def _managed_secret_manager(db_session: AsyncSession):
    return get_real_secret_manager(
        session=db_session,
        user_context=UserContext(
            user_id=PLATFORM_PRINCIPAL_ID,
            workspace_id=PLATFORM_WORKSPACE_ID,
        ),
    )


async def _managed_credentials(manager, key: str) -> tuple[str, str]:
    raw = await manager.get_secret(key)
    if not raw:
        raise HTTPException(
            status_code=503,
            detail="This connection is not configured by the AgentArea operator yet.",
        )
    try:
        value = json.loads(raw)
        client_id = str(value.get("client_id") or "")
        client_secret = str(value.get("client_secret") or "")
    except (json.JSONDecodeError, AttributeError) as exc:
        raise HTTPException(status_code=500, detail="Managed OAuth app secret is invalid") from exc
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Managed OAuth app secret is incomplete")
    return client_id, client_secret


@router.put(
    "/oauth/apps/{provider_key}",
    response_model=ManagedOAuthAppResponse,
    dependencies=[Depends(require_platform_catalog_write)],
)
async def configure_managed_oauth_app(
    provider_key: str,
    body: ManagedOAuthAppRequest,
    db_session: DatabaseSessionDep,
) -> ManagedOAuthAppResponse:
    """Configure one platform-wide OAuth app without exposing it to tenants."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,127}", provider_key):
        raise HTTPException(status_code=400, detail="Invalid provider key")
    manager = _managed_secret_manager(db_session)
    await manager.set_secret(
        f"{_MANAGED_CREDENTIALS_PREFIX}{provider_key}",
        json.dumps({"client_id": body.client_id, "client_secret": body.client_secret}),
    )
    return ManagedOAuthAppResponse(provider_key=provider_key, configured=True)


@router.post(
    "/catalog/{item_id}/connect",
    response_model=CatalogConnectionResponse,
)
async def connect_catalog_item(
    item_id: UUID,
    body: CatalogConnectionRequest,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> CatalogConnectionResponse:
    """Materialize a trusted OpenAPI template and start its OAuth flow."""
    item_repo = RegistryItemRepository(db_session, user_context)
    item = await item_repo.get_by_id(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Catalog connection not found")
    registry = await RegistryRepository(db_session, user_context).get_by_id(item.registry_id)
    spec = item.spec or {}
    if (
        registry is None
        or not registry.is_active
        or registry.registry_type != "mcp_servers"
        or spec.get("connection_type") != "openapi"
    ):
        raise HTTPException(
            status_code=400, detail="Catalog item is not a one-click API connection"
        )

    oauth = _oauth_profile(spec)
    base_url = str(spec.get("base_url") or "")
    base_origin = _origin(base_url)
    allowed_origins = oauth.get("allowed_api_origins") or [base_origin]
    if not isinstance(allowed_origins, list) or base_origin not in allowed_origins:
        raise HTTPException(status_code=500, detail="Catalog OAuth API origin is not allowlisted")
    if any(_origin(str(origin)) != origin for origin in allowed_origins):
        raise HTTPException(status_code=500, detail="Catalog OAuth origin must be an exact origin")

    workspace_secret_manager = get_real_secret_manager(
        session=db_session, user_context=user_context
    )
    platform_secret_manager = _managed_secret_manager(db_session)
    repository_factory = RepositoryFactory(db_session, user_context)
    if body.credential_mode == "managed":
        client_id, _ = await _managed_credentials(
            platform_secret_manager, str(oauth["managed_credentials_key"])
        )
        credentials: dict[str, Any] = {}
    else:
        if not body.client_id or not body.client_secret:
            raise HTTPException(
                status_code=422,
                detail="Custom OAuth app requires both client ID and client secret.",
            )
        client_id = body.client_id
        credentials = {"client_secret": body.client_secret}

    connection_service = OpenAPIConnectionService(
        repository_factory=repository_factory,
        secret_manager=workspace_secret_manager,
        allow_private_urls=get_settings().mcp.ALLOW_PRIVATE_URLS,
    )
    connection = await connection_service.get_by_registry_item_id(item_id)
    if connection is None:
        connection = await connection_service.create_connection(
            OpenAPIConnectionCreate(
                name=item.name,
                description=item.description,
                base_url=base_url,
                spec_url=spec.get("spec_url"),
                spec_content=spec.get("spec_content"),
            ),
            registry_item_id=item_id,
            allowed_auth_origins=[str(origin) for origin in allowed_origins],
            status="pending",
        )

    auth_service = MCPAuthService(
        MCPAuthConfigRepository(db_session, user_context),
        workspace_secret_manager,
        platform_secret_manager,
    )
    auth_config = await auth_service.create(
        name=f"{oauth['provider_key']}-{str(connection.id)[:8]}",
        auth_type="oauth2",
        config={
            "provider": oauth["provider_key"],
            "authorization_url": oauth["authorization_url"],
            "token_url": oauth["token_url"],
            "client_id": client_id,
            "scopes": oauth["scopes"],
            "authorization_scheme": oauth["authorization_scheme"],
            "client_auth_method": oauth["client_auth_method"],
            "credential_mode": body.credential_mode,
            "managed_credentials_key": oauth["managed_credentials_key"],
        },
        credentials=credentials,
        allow_managed_credentials=True,
    )

    pkce = PKCEPair.generate()
    state = secrets.token_urlsafe(32)
    await _store_state(
        state,
        {
            "connection_id": str(connection.id),
            "auth_config_id": str(auth_config.id),
            "workspace_id": str(user_context.workspace_id),
            "user_id": str(user_context.user_id),
            "code_verifier": pkce.verifier,
            "return_to": body.return_to,
        },
    )
    query = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": _callback_uri(),
        "scope": " ".join(oauth["scopes"]),
        "state": state,
        "code_challenge": pkce.challenge,
        "code_challenge_method": "S256",
    }
    authorize_url = f"{oauth['authorization_url']}?{urllib.parse.urlencode(query)}"
    return CatalogConnectionResponse(connection_id=connection.id, authorize_url=authorize_url)


@public_router.get("/oauth/callback")
async def oauth_callback(
    db_session: DatabaseSessionDep,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
):
    """Exchange an authorization code and attach tokens to the connection."""
    if not state:
        raise HTTPException(status_code=400, detail="Missing OAuth state")
    state_data = await _pop_state(state)
    if state_data is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    connection_id = UUID(state_data["connection_id"])
    frontend = _frontend_base(state_data.get("return_to", ""))
    detail_url = f"{frontend}/connections/openapi/{connection_id}"
    if error or not code:
        reason = urllib.parse.quote(error_description or error or "missing_code")
        return RedirectResponse(f"{detail_url}?oauth=error&reason={reason}", status_code=302)

    user_context = UserContext(
        user_id=state_data["user_id"],
        workspace_id=state_data["workspace_id"],
    )
    workspace_secret_manager = get_real_secret_manager(
        session=db_session, user_context=user_context
    )
    platform_secret_manager = _managed_secret_manager(db_session)
    auth_service = MCPAuthService(
        MCPAuthConfigRepository(db_session, user_context),
        workspace_secret_manager,
        platform_secret_manager,
    )
    auth_config = await auth_service.get(UUID(state_data["auth_config_id"]))
    if auth_config is None:
        raise HTTPException(status_code=400, detail="OAuth connection no longer exists")
    try:
        client_id, client_secret, credentials = await auth_service.get_oauth_client_credentials(
            auth_config,
            require_secret=True,
        )
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _callback_uri(),
            "code_verifier": state_data["code_verifier"],
            "client_id": client_id,
        }
        async with httpx.AsyncClient() as client:
            if auth_config.config.get("client_auth_method") == "client_secret_basic":
                response = await client.post(
                    auth_config.config["token_url"],
                    data=payload,
                    auth=(client_id, client_secret),
                    timeout=15,
                )
            else:
                payload["client_secret"] = client_secret
                response = await client.post(
                    auth_config.config["token_url"], data=payload, timeout=15
                )
            response.raise_for_status()
            tokens = response.json()
    except (httpx.HTTPError, MissingCredentialsError, ValueError) as exc:
        logger.warning("Connection OAuth exchange failed for %s: %s", connection_id, exc)
        return RedirectResponse(
            f"{detail_url}?oauth=error&reason=token_exchange_failed", status_code=302
        )

    access_token = str(tokens.get("access_token") or "")
    if not access_token:
        return RedirectResponse(f"{detail_url}?oauth=error&reason=no_access_token", status_code=302)
    credentials.update(
        {
            "access_token": access_token,
            "refresh_token": str(tokens.get("refresh_token") or ""),
            "token_type": str(tokens.get("token_type") or "bearer"),
            "scope": tokens.get("scope") or "",
        }
    )
    if tokens.get("expires_in") is not None:
        credentials["expires_at"] = time.time() + int(tokens["expires_in"])
    else:
        credentials.pop("expires_at", None)
    await auth_service.update(
        auth_config.id,
        credentials=credentials,
        allow_managed_credentials=True,
    )

    connection_repo = OpenAPIConnectionRepository(db_session, user_context)
    connection = await connection_repo.update(
        connection_id,
        auth_config_id=auth_config.id,
        status="active",
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    await db_session.commit()
    return RedirectResponse(f"{detail_url}?oauth=success", status_code=302)
