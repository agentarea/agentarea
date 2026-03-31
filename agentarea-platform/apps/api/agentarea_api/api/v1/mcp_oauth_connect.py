"""MCP OAuth Connect — client-side OAuth for connecting to remote MCP servers.

AgentArea acts as an MCP client. When a user wants to connect to a remote MCP
server that requires OAuth (e.g. GitHub Copilot), this module handles:

    GET /v1/mcp-oauth/authorize   — discover AS, register, redirect to auth page
    GET /v1/mcp-oauth/callback    — exchange code for token, store in MCPAuthConfig

Implements the client-side of:
    - MCP Authorization Spec (draft)
    - RFC 9728 (Protected Resource Metadata)
    - RFC 8414 (AS Metadata Discovery)
    - RFC 7591 (Dynamic Client Registration)
    - OAuth 2.1 + PKCE (S256)
"""

import json
import logging
import urllib.parse
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from agentarea_api.api.deps.services import (
    DatabaseSessionDep,
)
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.config import get_settings
from agentarea_common.infrastructure.connection_manager import get_connection_manager
from agentarea_mcp.application.oauth_client_service import (
    AuthServerMetadata,
    MCPOAuthClientService,
    MCPOAuthDiscoveryError,
    PKCEPair,
)
from agentarea_mcp.infrastructure.auth_repository import MCPAuthConfigRepository
from agentarea_mcp.application.auth_service import MCPAuthService

logger = logging.getLogger(__name__)

# Protected router (requires auth) — /authorize needs user context
router = APIRouter(prefix="/mcp-oauth", tags=["mcp-oauth-connect"])

# Public router (no auth) — /callback is a redirect from external AS
public_router = APIRouter(prefix="/mcp-oauth", tags=["mcp-oauth-connect"])

# Redis state TTL
_STATE_PREFIX = "mcp_oauth_client_state"
_STATE_TTL_SECONDS = 600  # 10 minutes


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------


async def _get_redis():
    from agentarea_common.events.redis_event_broker import RedisEventBroker

    cm = get_connection_manager()
    broker = await cm.get_event_broker()
    if isinstance(broker, RedisEventBroker):
        await broker._ensure_connected()
        if broker._raw_redis is not None:
            return broker._raw_redis
        # Fallback: create a raw client
        return await broker._create_raw_redis()
    raise HTTPException(status_code=500, detail="Redis not available")


async def _store_state(redis, state: str, payload: dict) -> None:
    await redis.set(f"{_STATE_PREFIX}:{state}", json.dumps(payload), ex=_STATE_TTL_SECONDS)


async def _pop_state(redis, state: str) -> dict | None:
    key = f"{_STATE_PREFIX}:{state}"
    raw = await redis.get(key)
    if raw is None:
        return None
    await redis.delete(key)
    return json.loads(raw)


def _callback_uri(request: Request) -> str:
    """Build the absolute callback URI for this request's host."""
    settings = get_settings()
    api_base = settings.app.API_BASE_URL.rstrip("/")
    return f"{api_base}/v1/mcp-oauth/callback"


def _safe_frontend_base(return_to: str) -> str:
    """Validate and normalize frontend redirect base URL.

    Allows:
    - empty return_to (falls back to FRONTEND_BASE_URL)
    - absolute URL with same origin as FRONTEND_BASE_URL
    """
    settings = get_settings()
    default_base = settings.app.FRONTEND_BASE_URL.rstrip("/")
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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/authorize")
async def oauth_authorize(
    request: Request,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
    instance_id: UUID = Query(..., description="MCP instance to connect"),
    return_to: str = Query("", description="Frontend URL to redirect after OAuth completes"),
):
    """Initiate MCP OAuth flow: discover AS, register client, redirect to auth page.

    1. Look up the MCP instance's remote URL
    2. Discover the authorization server (RFC 9728 → RFC 8414)
    3. Dynamically register as an OAuth client (RFC 7591)
    4. Generate PKCE pair and state
    5. Redirect user to the authorization endpoint
    """
    from agentarea_mcp.infrastructure.repository import MCPServerInstanceRepository

    # Fetch the instance to get its remote URL
    instance_repo = MCPServerInstanceRepository(db_session, user_context)
    instance = await instance_repo.get_by_id(instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="MCP instance not found")

    json_spec = instance.json_spec or {}
    mcp_url = json_spec.get("endpoint_url") or json_spec.get("url")
    if not mcp_url:
        raise HTTPException(
            status_code=400,
            detail="Instance has no remote URL configured. OAuth connect requires a URL-type MCP instance.",
        )

    # Discover the authorization server
    oauth_client = MCPOAuthClientService()
    try:
        as_metadata = await oauth_client.discover_auth_server(mcp_url)
    except MCPOAuthDiscoveryError as exc:
        raise HTTPException(status_code=502, detail=f"OAuth discovery failed: {exc}") from exc

    # Client Registration — try DCR first, fall back to env-var credentials
    redirect_uri = _callback_uri(request)
    client_creds = None

    if as_metadata.registration_endpoint:
        try:
            client_creds = await oauth_client.register_client(as_metadata, redirect_uri)
        except MCPOAuthDiscoveryError:
            logger.info("DCR failed for %s, trying env-var credentials", as_metadata.issuer)

    if client_creds is None:
        # Fall back to pre-registered credentials from env vars
        import os
        client_id = os.environ.get("MCP_OAUTH_CLIENT_ID", "")
        client_secret = os.environ.get("MCP_OAUTH_CLIENT_SECRET", "")
        if not client_id:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Authorization server {as_metadata.issuer} does not support "
                    "Dynamic Client Registration. Set MCP_OAUTH_CLIENT_ID and "
                    "MCP_OAUTH_CLIENT_SECRET environment variables with your "
                    "registered OAuth App credentials."
                ),
            )
        from agentarea_mcp.application.oauth_client_service import OAuthClientCredentials
        client_creds = OAuthClientCredentials(client_id=client_id, client_secret=client_secret)

    # Generate PKCE pair and state token
    pkce = PKCEPair.generate()
    import secrets
    state = secrets.token_urlsafe(32)

    # Store everything in Redis so the callback can complete the flow
    redis = await _get_redis()
    await _store_state(redis, state, {
        "instance_id": str(instance_id),
        "workspace_id": str(user_context.workspace_id),
        "user_id": str(user_context.user_id),
        "mcp_url": mcp_url,
        "code_verifier": pkce.verifier,
        "client_id": client_creds.client_id,
        "client_secret": client_creds.client_secret,
        "return_to": return_to,
        "as_metadata": {
            "issuer": as_metadata.issuer,
            "authorization_endpoint": as_metadata.authorization_endpoint,
            "token_endpoint": as_metadata.token_endpoint,
            "resource": as_metadata.resource,
        },
    })

    # Build authorization URL
    auth_url = oauth_client.build_authorize_url(
        as_metadata=as_metadata,
        client_id=client_creds.client_id,
        redirect_uri=redirect_uri,
        pkce=pkce,
        state=state,
    )
    return {"authorize_url": auth_url}


@public_router.get("/callback")
async def oauth_callback(
    request: Request,
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
        # No state data yet — fall back to relative redirect
        reason = urllib.parse.quote(error_description or error)
        return RedirectResponse(url=f"/mcp-servers?oauth=error&reason={reason}", status_code=302)

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state parameter")

    # Validate and consume state
    redis = await _get_redis()
    state_data = await _pop_state(redis, state)
    if state_data is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    instance_id = state_data["instance_id"]
    # return_to is the frontend origin stored during /authorize
    frontend_base = _safe_frontend_base(state_data.get("return_to", ""))
    as_meta_dict = state_data["as_metadata"]
    as_metadata = AuthServerMetadata(
        issuer=as_meta_dict["issuer"],
        authorization_endpoint=as_meta_dict["authorization_endpoint"],
        token_endpoint=as_meta_dict["token_endpoint"],
        resource=as_meta_dict.get("resource", ""),
    )

    # Exchange code for tokens
    oauth_client = MCPOAuthClientService()
    redirect_uri = _callback_uri(request)
    try:
        tokens = await oauth_client.exchange_code(
            as_metadata=as_metadata,
            code=code,
            client_id=state_data["client_id"],
            redirect_uri=redirect_uri,
            code_verifier=state_data["code_verifier"],
            client_secret=state_data.get("client_secret"),
        )
    except Exception as exc:
        logger.error("OAuth token exchange failed: %s", exc)
        return RedirectResponse(
            url=f"{frontend_base}/mcp-servers/{instance_id}?oauth=error&reason=token_exchange_failed",
            status_code=302,
        )

    access_token = tokens.get("access_token", "")
    if not access_token:
        return RedirectResponse(
            url=f"{frontend_base}/mcp-servers/{instance_id}?oauth=error&reason=no_access_token",
            status_code=302,
        )

    # Create MCPAuthConfig with the token
    from agentarea_common.auth.context import UserContext

    user_context = UserContext(
        user_id=state_data["user_id"],
        workspace_id=state_data["workspace_id"],
    )
    auth_repo = MCPAuthConfigRepository(db_session, user_context)
    from agentarea_api.api.deps.services import get_real_secret_manager
    secret_manager = get_real_secret_manager(session=db_session, user_context=user_context)
    auth_service = MCPAuthService(auth_repo, secret_manager)

    auth_config = await auth_service.create(
        name=f"mcp-oauth-{instance_id[:8]}",
        auth_type="oauth2",
        config={
            "provider": "mcp-remote",
            "token_url": as_metadata.token_endpoint,
            "client_id": state_data["client_id"],
            "issuer": as_metadata.issuer,
        },
        credentials={
            "access_token": access_token,
            "token_type": tokens.get("token_type", "bearer"),
            "refresh_token": tokens.get("refresh_token", ""),
            "scope": tokens.get("scope", ""),
        },
    )

    # Link auth config to the MCP instance and mark as running
    from agentarea_mcp.infrastructure.repository import MCPServerInstanceRepository

    instance_repo = MCPServerInstanceRepository(db_session, user_context)
    await instance_repo.update(UUID(instance_id), auth_config_id=auth_config.id, status="connected")
    await db_session.commit()

    logger.info(
        "MCP OAuth connect complete: instance=%s auth_config=%s issuer=%s",
        instance_id, auth_config.id, as_metadata.issuer,
    )

    # Trigger tool discovery in background — don't block the redirect
    try:
        from agentarea_mcp.application.service import MCPServerInstanceService
        from agentarea_common.events.broker import EventBroker

        # Build service with the same session context
        from agentarea_common.base.repository_factory import RepositoryFactory
        factory = RepositoryFactory(session=db_session, user_context=user_context)
        # Event broker is optional for tool discovery
        service = MCPServerInstanceService(
            repository_factory=factory,
            event_broker=None,
            secret_manager=secret_manager,
        )
        # Fire and forget — don't block the user redirect
        import asyncio
        asyncio.ensure_future(_discover_after_oauth(service, UUID(instance_id), db_session))
    except Exception as discover_err:
        logger.warning("Failed to schedule tool discovery after OAuth: %s", discover_err)

    return RedirectResponse(
        url=f"{frontend_base}/mcp-servers/{instance_id}?oauth=success",
        status_code=302,
    )


async def _discover_after_oauth(
    service, instance_id: UUID, db_session,
) -> None:
    """Background task: discover tools after OAuth connect completes."""
    try:
        success = await service.discover_and_store_tools(instance_id)
        if success:
            logger.info("Post-OAuth tool discovery succeeded for %s", instance_id)
        else:
            logger.warning("Post-OAuth tool discovery returned False for %s", instance_id)
    except Exception as e:
        logger.warning("Post-OAuth tool discovery failed for %s: %s", instance_id, e)
