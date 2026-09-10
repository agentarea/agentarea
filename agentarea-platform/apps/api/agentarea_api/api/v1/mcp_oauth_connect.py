"""MCP OAuth Connect — client-side OAuth for connecting to remote MCP servers.

AgentArea acts as an MCP client. When a user wants to connect to a remote MCP
server that requires OAuth (e.g. GitHub Copilot), this module handles:

    GET  /v1/mcp-oauth/preflight  — can this server be authorized, and with what
    POST /v1/mcp-oauth/authorize  — discover AS, register or accept an OAuth app,
                                    redirect to the auth page
    GET  /v1/mcp-oauth/callback   — exchange code for token, store in MCPAuthConfig

Preflight exists so the UI never offers a Connect button that cannot complete:
providers without Dynamic Client Registration (Google, GitHub) need the
workspace's own OAuth app, and that has to be asked for before the redirect,
not discovered as an error after it.

Implements the client-side of:
    - MCP Authorization Spec (draft)
    - RFC 9728 (Protected Resource Metadata)
    - RFC 8414 (AS Metadata Discovery)
    - RFC 7591 (Dynamic Client Registration)
    - OAuth 2.1 + PKCE (S256)
"""

import asyncio
import json
import logging
import secrets
import time
import urllib.parse
from typing import Any, Literal
from uuid import UUID

from agentarea_api.api.deps.services import (
    DatabaseSessionDep,
    SecretCatalogServiceDep,
    get_real_secret_manager,
)
from agentarea_api.api.v1.oauth_app_credentials import (
    CustomOAuthAppFields,
    ResolvedOAuthApp,
    resolve_custom_oauth_app,
)
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.route_authz import enforced_in_handler, unrestricted
from agentarea_common.config import get_settings
from agentarea_common.config.database import get_database
from agentarea_common.events.broker import EventBroker
from agentarea_common.infrastructure.connection_manager import get_connection_manager
from agentarea_mcp.application.auth_service import MCPAuthService
from agentarea_mcp.application.oauth_client_service import (
    AuthServerMetadata,
    MCPOAuthClientService,
    MCPOAuthDiscoveryError,
    PKCEPair,
)
from agentarea_mcp.infrastructure.auth_repository import MCPAuthConfigRepository
from agentarea_mcp.infrastructure.repository import (
    MCPServerInstanceRepository,
    MCPServerRepository,
)
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)
_background_tasks: set = set()


class _NoopEventBroker(EventBroker):
    async def publish(self, event: Any) -> None:
        return None


# Protected router (requires auth) — /authorize needs user context
router = APIRouter(prefix="/mcp-oauth", tags=["mcp-oauth-connect"])

# Public router (no auth) — /callback is a redirect from external AS
public_router = APIRouter(prefix="/mcp-oauth", tags=["mcp-oauth-connect"])

# Redis state TTL
_STATE_PREFIX = "mcp_oauth_client_state"
_STATE_TTL_SECONDS = 600  # 10 minutes


class MCPOAuthAuthorizeRequest(CustomOAuthAppFields):
    """Start an OAuth flow for one MCP instance.

    ``auto`` registers AgentArea with the authorization server (RFC 7591).
    ``custom`` uses an OAuth app the workspace registered with the provider —
    the only option when the provider has no Dynamic Client Registration.
    """

    model_config = ConfigDict(extra="forbid")

    instance_id: UUID
    credential_mode: Literal["auto", "custom"] = "auto"
    return_to: str = Field(default="", max_length=2048)

    @model_validator(mode="after")
    def validate_credential_sources(self) -> "MCPOAuthAuthorizeRequest":
        if self.credential_mode == "auto":
            if self.has_any_custom_credential():
                raise ValueError(
                    "Automatically registered connections do not accept custom OAuth credentials."
                )
            return self
        self.validate_custom_credential_sources()
        return self


class MCPOAuthPreflightResponse(BaseModel):
    """What the UI needs before it can offer a Connect action.

    ``ready`` — Connect can run unattended (the server supports DCR).
    ``oauth_app_required`` — ask for a client ID/secret first.
    ``unsupported`` — this server cannot be authorized this way; say why.
    """

    instance_id: UUID
    status: Literal["ready", "oauth_app_required", "unsupported"]
    connected: bool
    detail: str = ""
    issuer: str | None = None
    authorization_endpoint: str | None = None
    scopes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------


async def _get_redis():
    from agentarea_common.events.redis_event_broker import RedisEventBroker

    cm = get_connection_manager()
    broker = await cm.get_event_broker()
    if isinstance(broker, RedisEventBroker):
        await broker._ensure_connected()
        if broker.raw_redis is not None:
            return broker.raw_redis
    raise HTTPException(status_code=500, detail="Redis not available")


async def _store_state(state: str, payload: dict) -> None:
    redis = await _get_redis()
    await redis.set(f"{_STATE_PREFIX}:{state}", json.dumps(payload), ex=_STATE_TTL_SECONDS)


async def _pop_state(state: str) -> dict | None:
    redis = await _get_redis()
    # Consume in one operation so a replayed callback cannot exchange the same
    # authorization code twice.
    raw = await redis.getdel(f"{_STATE_PREFIX}:{state}")
    if raw is None:
        return None
    return json.loads(raw)


def _callback_uri() -> str:
    """Build the absolute callback URI this deployment is reachable at."""
    settings = get_settings()
    api_base = settings.app.API_URL.rstrip("/")
    return f"{api_base}/v1/mcp-oauth/callback"


def _resolve_instance_remote_url(server_spec) -> str | None:
    """Resolve the remote MCP URL from the parent MCPServer.

    Transport fields live on the server: the URL comes from its remote_url
    column, falling back to the URL in its json_spec.
    """
    if server_spec is None:
        return None
    if getattr(server_spec, "remote_url", None):
        return server_spec.remote_url
    spec_json = getattr(server_spec, "json_spec", None) or {}
    if spec_json.get("type") == "url":
        return spec_json.get("endpoint_url") or spec_json.get("url")
    return None


async def _load_instance_and_url(
    instance_id: UUID, user_context: UserContext, db_session
) -> tuple[Any, str | None]:
    """Fetch a workspace-scoped instance together with its remote MCP URL."""
    instance_repo = MCPServerInstanceRepository(db_session, user_context)
    instance = await instance_repo.get_by_id(instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="MCP instance not found")

    server_spec = None
    if instance.server_spec_id:
        server_repo = MCPServerRepository(db_session, user_context)
        server_spec = await server_repo.get_server_by_id(instance.server_spec_id)
    return instance, _resolve_instance_remote_url(server_spec)


def _oauth_app_required_detail(issuer: str) -> str:
    return (
        f"{issuer} does not support Dynamic Client Registration (RFC 7591), so AgentArea "
        "cannot register itself. Register an OAuth app with this provider and connect with "
        "its client ID and secret."
    )


def _safe_frontend_base(return_to: str) -> str:
    """Validate and normalize frontend redirect base URL.

    Allows:
    - empty return_to (falls back to FRONTEND_BASE_URL)
    - absolute URL with same origin as FRONTEND_BASE_URL
    """
    settings = get_settings()
    default_base = settings.app.APP_URL.rstrip("/")
    if not return_to:
        return default_base

    try:
        parsed = urllib.parse.urlparse(return_to)
        default_parsed = urllib.parse.urlparse(default_base)
    except Exception:
        return default_base

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return default_base

    if parsed.scheme != default_parsed.scheme or parsed.netloc != default_parsed.netloc:
        logger.warning("Rejected non-matching return_to origin: %s", return_to)
        return default_base

    return f"{parsed.scheme}://{parsed.netloc}"


def _instance_detail_url(frontend_base: str, instance_id: str) -> str:
    """Where the browser lands once the authorization server sends it back.

    Named once because it used to be spelled inline at every redirect, all of
    them still pointing at /mcp-servers after the page moved to /connections.
    """
    return f"{frontend_base}/connections/{instance_id}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/preflight",
    response_model=MCPOAuthPreflightResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def oauth_preflight(
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
    instance_id: UUID = Query(..., description="MCP instance to inspect"),
) -> MCPOAuthPreflightResponse:
    """Report whether this instance can be authorized, and with what.

    Every outcome is a 200: "this server has no OAuth" is an answer the UI
    renders, not a failure it has to decode from an error response.
    """
    instance, mcp_url = await _load_instance_and_url(instance_id, user_context, db_session)
    connected = instance.auth_config_id is not None

    def _unsupported(detail: str) -> MCPOAuthPreflightResponse:
        return MCPOAuthPreflightResponse(
            instance_id=instance_id,
            status="unsupported",
            connected=connected,
            detail=detail,
        )

    if not mcp_url:
        return _unsupported(
            "Instance has no remote URL configured. OAuth connect requires a URL-type MCP instance."
        )

    try:
        as_metadata = await MCPOAuthClientService().discover_auth_server(mcp_url)
    except MCPOAuthDiscoveryError as exc:
        return _unsupported(str(exc))

    status: Literal["ready", "oauth_app_required"] = (
        "ready" if as_metadata.registration_endpoint else "oauth_app_required"
    )
    return MCPOAuthPreflightResponse(
        instance_id=instance_id,
        status=status,
        connected=connected,
        detail="" if status == "ready" else _oauth_app_required_detail(as_metadata.issuer),
        issuer=as_metadata.issuer,
        authorization_endpoint=as_metadata.authorization_endpoint,
        scopes=list(as_metadata.scopes_supported),
    )


@router.post(
    "/authorize",
    dependencies=[unrestricted("OAuth authorization endpoint; unauthenticated by protocol")],
)
async def oauth_authorize(
    body: MCPOAuthAuthorizeRequest,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
    secret_catalog: SecretCatalogServiceDep,
) -> dict[str, str]:
    """Initiate MCP OAuth flow and return the URL to send the user to.

    1. Look up the MCP instance's remote URL
    2. Discover the authorization server (RFC 9728 → RFC 8414)
    3. Register dynamically (RFC 7591), or take the workspace's own OAuth app
    4. Persist the client credentials on an auth config
    5. Generate PKCE pair and state, and build the authorization URL
    """
    instance, mcp_url = await _load_instance_and_url(body.instance_id, user_context, db_session)
    if not mcp_url:
        raise HTTPException(
            status_code=400,
            detail="Instance has no remote URL configured. OAuth connect requires a URL-type MCP instance.",
        )

    oauth_client = MCPOAuthClientService()
    try:
        as_metadata = await oauth_client.discover_auth_server(mcp_url)
    except MCPOAuthDiscoveryError as exc:
        raise HTTPException(status_code=502, detail=f"OAuth discovery failed: {exc}") from exc

    workspace_secret_manager = get_real_secret_manager(
        session=db_session, user_context=user_context
    )
    redirect_uri = _callback_uri()

    if body.credential_mode == "custom":
        resolved = await resolve_custom_oauth_app(
            body, catalog=secret_catalog, manager=workspace_secret_manager
        )
    else:
        # Dynamic registration or nothing: a shared server-wide OAuth app would
        # silently authorize one workspace's users through another workspace's
        # client, so the workspace's own app is the only alternative.
        if not as_metadata.registration_endpoint:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "oauth_app_required",
                    "message": _oauth_app_required_detail(as_metadata.issuer),
                    "issuer": as_metadata.issuer,
                },
            )
        try:
            client_creds = await oauth_client.register_client(as_metadata, redirect_uri)
        except Exception as exc:
            logger.info("DCR failed for %s: %s", as_metadata.issuer, exc, exc_info=True)
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "oauth_app_required",
                    "message": (
                        f"Dynamic client registration with {as_metadata.issuer} failed "
                        f"({exc}). Connect with an OAuth app you registered with this provider."
                    ),
                    "issuer": as_metadata.issuer,
                },
            ) from exc
        resolved = ResolvedOAuthApp(
            client_id=client_creds.client_id,
            config={"client_id": client_creds.client_id},
            credentials=(
                {"client_secret": client_creds.client_secret} if client_creds.client_secret else {}
            ),
        )

    auth_service = MCPAuthService(
        MCPAuthConfigRepository(db_session, user_context), workspace_secret_manager
    )
    # Persist the client credentials before redirecting: they are needed again at
    # token exchange and at every refresh, so OAuth state carries a reference to
    # them rather than a copy of the secret.
    auth_config = await auth_service.create(
        name=f"mcp-oauth-{str(instance.id)[:8]}",
        auth_type="oauth2",
        config={
            "provider": "mcp-remote",
            "issuer": as_metadata.issuer,
            "token_url": as_metadata.token_endpoint,
            "authorization_url": as_metadata.authorization_endpoint,
            "scopes": list(as_metadata.scopes_supported),
            "credential_mode": body.credential_mode,
            **resolved.config,
        },
        credentials=resolved.credentials,
        allow_managed_credentials=bool(resolved.references),
    )
    for secret_id, field_name in resolved.references:
        await secret_catalog.add_reference(
            secret_id, "mcp_auth_config", str(auth_config.id), field_name
        )

    pkce = PKCEPair.generate()
    state = secrets.token_urlsafe(32)
    await _store_state(
        state,
        {
            "instance_id": str(instance.id),
            "auth_config_id": str(auth_config.id),
            "workspace_id": str(user_context.workspace_id),
            "user_id": str(user_context.user_id),
            "code_verifier": pkce.verifier,
            "return_to": body.return_to,
            "as_metadata": {
                "issuer": as_metadata.issuer,
                "authorization_endpoint": as_metadata.authorization_endpoint,
                "token_endpoint": as_metadata.token_endpoint,
                "resource": as_metadata.resource,
            },
        },
    )

    auth_url = oauth_client.build_authorize_url(
        as_metadata=as_metadata,
        client_id=resolved.client_id,
        redirect_uri=redirect_uri,
        pkce=pkce,
        state=state,
    )
    return {"authorize_url": auth_url}


@public_router.get(
    "/callback",
    dependencies=[
        enforced_in_handler("the signed OAuth state token is the only credential this callback has")
    ],
)
async def oauth_callback(
    db_session: DatabaseSessionDep,
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    error_description: str = Query(None),
):
    """OAuth callback — exchange code for token and store in MCPAuthConfig.

    This endpoint does NOT require auth (the user is mid-redirect from the
    remote AS). The state token proves the flow was initiated by our /authorize.
    """
    if error:
        # The state is not read on this branch, so there is no stored return_to:
        # land on the configured frontend, with the reason carried as query data.
        query = urllib.parse.urlencode({"oauth": "error", "reason": error_description or error})
        return RedirectResponse(
            url=f"{_safe_frontend_base('')}/connections?{query}", status_code=302
        )

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state parameter")

    state_data = await _pop_state(state)
    if state_data is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    instance_id = state_data["instance_id"]
    # return_to is the frontend origin stored during /authorize
    frontend_base = _safe_frontend_base(state_data.get("return_to", ""))
    detail_url = _instance_detail_url(frontend_base, instance_id)
    as_meta_dict = state_data["as_metadata"]
    as_metadata = AuthServerMetadata(
        issuer=as_meta_dict["issuer"],
        authorization_endpoint=as_meta_dict["authorization_endpoint"],
        token_endpoint=as_meta_dict["token_endpoint"],
        resource=as_meta_dict.get("resource", ""),
    )

    user_context = UserContext(
        user_id=state_data["user_id"],
        workspace_id=state_data["workspace_id"],
    )
    secret_manager = get_real_secret_manager(session=db_session, user_context=user_context)
    auth_service = MCPAuthService(MCPAuthConfigRepository(db_session, user_context), secret_manager)
    auth_config = await auth_service.get(UUID(state_data["auth_config_id"]))
    if auth_config is None:
        raise HTTPException(status_code=400, detail="OAuth connection no longer exists")

    oauth_client = MCPOAuthClientService()
    try:
        # PKCE public clients have no secret; confidential ones (custom OAuth
        # apps, and DCR servers that issue one) do.
        (
            client_id,
            client_secret,
            credentials,
        ) = await auth_service.get_oauth_client_credentials(auth_config)
        tokens = await oauth_client.exchange_code(
            as_metadata=as_metadata,
            code=code,
            client_id=client_id,
            redirect_uri=_callback_uri(),
            code_verifier=state_data["code_verifier"],
            client_secret=client_secret or None,
        )
    except Exception as exc:
        logger.error("OAuth token exchange failed: %s", exc, exc_info=True)
        return RedirectResponse(
            url=f"{detail_url}?oauth=error&reason=token_exchange_failed",
            status_code=302,
        )

    access_token = tokens.get("access_token", "")
    if not access_token:
        return RedirectResponse(
            url=f"{detail_url}?oauth=error&reason=no_access_token",
            status_code=302,
        )

    # Compute absolute expiry so auth_service doesn't trigger an immediate refresh.
    expires_in_raw = tokens.get("expires_in")
    try:
        expires_in_seconds = int(expires_in_raw) if expires_in_raw is not None else 3600
    except (TypeError, ValueError):
        expires_in_seconds = 3600

    credentials.update(
        {
            "access_token": access_token,
            "token_type": tokens.get("token_type", "bearer"),
            "refresh_token": tokens.get("refresh_token", ""),
            "scope": tokens.get("scope", ""),
            "expires_at": time.time() + expires_in_seconds,
        }
    )
    await auth_service.update(
        auth_config.id,
        credentials=credentials,
        allow_managed_credentials=True,
    )

    instance_repo = MCPServerInstanceRepository(db_session, user_context)
    await instance_repo.update(UUID(instance_id), auth_config_id=auth_config.id)
    await db_session.commit()

    logger.info(
        "MCP OAuth connect complete: instance=%s auth_config=%s issuer=%s",
        instance_id,
        auth_config.id,
        as_metadata.issuer,
    )

    # Discovery must not block the redirect; it runs after this request's session is closed.
    task = asyncio.create_task(_discover_after_oauth(user_context, UUID(instance_id)))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return RedirectResponse(
        url=f"{detail_url}?oauth=success",
        status_code=302,
    )


async def _discover_after_oauth(user_context: UserContext, instance_id: UUID) -> None:
    """Background task: discover tools after OAuth connect completes, on its own session."""
    from agentarea_common.base.repository_factory import RepositoryFactory
    from agentarea_mcp.application.service import MCPServerInstanceService

    try:
        async with get_database().session() as session:
            service = MCPServerInstanceService(
                repository_factory=RepositoryFactory(session=session, user_context=user_context),
                event_broker=_NoopEventBroker(),
                secret_manager=get_real_secret_manager(session=session, user_context=user_context),
            )
            success = await service.discover_and_store_tools(instance_id)
        if success:
            logger.info("Post-OAuth tool discovery succeeded for %s", instance_id)
        else:
            logger.warning("Post-OAuth tool discovery returned False for %s", instance_id)
    except Exception:
        logger.exception("Post-OAuth tool discovery failed for %s", instance_id)
