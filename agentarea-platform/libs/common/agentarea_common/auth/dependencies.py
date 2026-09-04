"""FastAPI dependencies for authentication and authorization.

This module provides reusable authentication dependencies that can be applied
at the router or endpoint level, following FastAPI best practices.

Provides:
- get_user_context: Required authentication (raises 401 if missing)
- get_optional_user: Optional authentication (returns None if missing)
- verify_workspace_access: Verify user has access to specific workspace
"""

import hashlib
import logging
from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .authorization import AuthorizationService
from .context import UserContext
from .context_manager import ContextManager
from .interfaces import AuthResult
from .providers.factory import AuthProviderFactory

logger = logging.getLogger(__name__)

_API_KEY_PREFIX = "aat_"


def _www_authenticate_bearer() -> str:
    """Return WWW-Authenticate header value with RFC 9728 resource_metadata.

    MCP clients (Cursor, Claude Desktop) use the resource_metadata URL to
    discover OAuth authorization server metadata and start the OAuth flow.
    """
    from agentarea_common.config import get_settings

    api_base = get_settings().app.API_BASE_URL.rstrip("/")
    return f'Bearer resource_metadata="{api_base}/.well-known/oauth-protected-resource"'


async def _resolve_accessible_workspaces(user_context: UserContext) -> None:
    """Populate accessible_workspaces on UserContext.

    Combines the policy-level static list from ``AuthorizationService``
    (own workspace + system workspace, plus enterprise overrides) with
    the dynamic list of workspaces the user has joined. Membership resolution
    lives at the request boundary, not inside ``AuthorizationService``, so the
    auth domain service has no infrastructure dependencies and stays
    singleton-safe.
    """
    from agentarea_common.di.container import resolve
    from agentarea_common.workspaces.memberships import (
        get_workspace_membership_graph,
        list_workspace_ids_for_member,
    )

    authz = resolve(AuthorizationService)
    accessible = list(await authz.get_accessible_workspaces(user_context))

    try:
        graph = get_workspace_membership_graph()
        member_workspace_ids = (
            await list_workspace_ids_for_member(graph, user_context.user_id)
            if graph is not None
            else []
        )
        for workspace_id in member_workspace_ids:
            if workspace_id not in accessible:
                accessible.append(workspace_id)
    except Exception as exc:
        # Membership lookup failures must not lock the user out of their own
        # workspace. Do not fall back to DB membership; graph grants are the
        # membership source of truth.
        logger.warning(
            "Could not resolve workspace memberships for user %s: %s",
            user_context.user_id,
            exc,
            exc_info=True,
        )

    user_context.accessible_workspaces = accessible


def _apply_workspace_override(user_context: UserContext, requested: str | None) -> None:
    """Validate and apply an optional X-Workspace-ID header override.

    Without this guard, any authenticated user could read/write another
    workspace by setting X-Workspace-ID to that workspace's id.
    """
    if not requested or requested == user_context.workspace_id:
        return
    accessible = user_context.accessible_workspaces or [user_context.workspace_id]
    if requested not in accessible:
        logger.warning(
            "Rejected X-Workspace-ID override: user=%s requested=%s accessible=%s",
            user_context.user_id,
            requested,
            accessible,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of the requested workspace",
        )
    user_context.workspace_id = requested


async def _resolve_workspace_id_from_slug(slug: str) -> str | None:
    """Map a workspace slug to its id, or None if no such workspace.

    Membership is NOT checked here — that stays in
    ``_apply_workspace_override``, the single authorization gate.
    """
    from agentarea_common.config.database import get_database
    from agentarea_common.workspaces.repository import WorkspaceRepository

    try:
        database = get_database()
        async with database.async_session_factory() as session:
            workspace = await WorkspaceRepository(session).get_by_slug(slug)
            return workspace.id if workspace else None
    except Exception:
        logger.warning("Could not resolve workspace slug %r", slug, exc_info=True)
        return None


async def _apply_workspace_selection(user_context: UserContext, request: Request) -> None:
    """Select the active workspace from request headers, then authorize it.

    Accepts either ``X-Workspace-ID`` (used by API clients that know the
    id) or ``X-Workspace-Slug`` (used by the web app, which carries the
    slug from the ``/w/{slug}`` URL). The slug is resolved to an id and
    then validated against ``accessible_workspaces`` exactly like the id
    path — the membership check is the security boundary, not the
    transport. An unknown slug is rejected as forbidden so we don't leak
    which workspaces exist.
    """
    requested = request.headers.get("X-Workspace-ID")
    if not requested:
        slug = request.headers.get("X-Workspace-Slug")
        if slug:
            requested = await _resolve_workspace_id_from_slug(slug)
            if requested is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User is not a member of the requested workspace",
                )
    _apply_workspace_override(user_context, requested)


# Security schemes
# Required authentication - raises 401 with RFC 9728 resource_metadata if no token
# NOTE: We use auto_error=False and raise manually so the WWW-Authenticate header
# includes the resource_metadata URL that MCP clients need for OAuth discovery.
security_required = HTTPBearer(auto_error=False)

# Optional authentication - returns None if no token (doesn't raise error)
security_optional = HTTPBearer(auto_error=False)


async def _validate_api_key(token: str, request: Request) -> UserContext | None:
    """Validate an API key and return UserContext, or None if invalid."""
    from agentarea_mcp.domain.auth_models import APIKey
    from sqlalchemy import select
    from sqlalchemy import update as sa_update

    from agentarea_common.config import get_database

    token_hash = hashlib.sha256(token.encode()).hexdigest()

    async with get_database().async_session_factory() as session:
        result = await session.execute(select(APIKey).where(APIKey.token_hash == token_hash))
        record = result.scalar_one_or_none()

        if record is None or not record.is_active:
            return None
        if record.expires_at and datetime.utcnow() >= record.expires_at:
            return None

        # Increment access count (best-effort)
        try:
            await session.execute(
                sa_update(APIKey)
                .where(APIKey.id == record.id)
                .values(
                    access_count=APIKey.access_count + 1,
                    last_accessed_at=datetime.utcnow(),
                )
            )
            await session.commit()
        except Exception:
            logger.debug("Failed to increment API key access count", exc_info=True)

        # Default to the workspace the API key was issued for. Any X-Workspace-ID
        # override is applied in get_user_context/get_optional_user AFTER
        # accessible_workspaces has been resolved, so it cannot escape the key
        # owner's membership.
        return UserContext(
            user_id=str(record.created_by),
            workspace_id=str(record.workspace_id),
        )


def get_auth_provider():
    """Get the configured authentication provider.

    Returns configured Kratos auth provider from application settings.
    """
    from agentarea_common.config.auth import get_auth_settings

    settings = get_auth_settings()

    return AuthProviderFactory.create_provider(
        "kratos",
        config={
            "jwks_b64": settings.KRATOS_JWKS_B64,
            "issuer": settings.KRATOS_ISSUER,
            "audience": settings.KRATOS_AUDIENCE,
        },
    )


# ---------------------------------------------------------------------------
# Hydra OAuth token validation (for MCP clients: Cursor, Claude Desktop)
# ---------------------------------------------------------------------------
_hydra_jwks_client = None


def _get_hydra_jwks():
    """Get or create Hydra JWKS client (cached)."""
    global _hydra_jwks_client
    if _hydra_jwks_client is not None:
        return _hydra_jwks_client

    import jwt as pyjwt

    from agentarea_common.config import get_settings

    settings = get_settings()
    jwks_url = f"{settings.mcp.HYDRA_PUBLIC_URL.rstrip('/')}/.well-known/jwks.json"
    _hydra_jwks_client = pyjwt.PyJWKClient(jwks_url, cache_keys=True)
    logger.info(f"Hydra JWKS client initialized: {jwks_url}")
    return _hydra_jwks_client


async def _try_hydra_token(token: str, request: Request) -> UserContext | None:
    """Try to validate a JWT as a Hydra-issued OAuth token.

    Returns UserContext if valid, None otherwise. Used as a fallback when
    Kratos validation fails — MCP clients (Cursor, Claude Desktop) authenticate
    via Hydra OAuth 2.1 and their tokens are signed with Hydra's keys.
    """
    import jwt as pyjwt

    from agentarea_common.config import get_settings

    try:
        jwks_client = _get_hydra_jwks()
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        # Audience verification is mandatory. It used to be toggled by whether
        # HYDRA_AUDIENCE happened to be set, and it was set in no chart, compose
        # file or env template — so `aud` was never checked anywhere, and any
        # token Hydra had ever signed was accepted on every protected route.
        #
        # An unset HYDRA_AUDIENCE now DISABLES this auth path rather than
        # weakening it: deployments that do not run Hydra (the prod compose does
        # not) keep working, and deployments that do must say which audience they
        # accept.
        hydra_audience = get_settings().mcp.HYDRA_AUDIENCE
        if not hydra_audience:
            logger.warning(
                "Hydra bearer token presented but HYDRA_AUDIENCE is not configured; "
                "refusing the token. Set HYDRA_AUDIENCE to this API's resource "
                "identifier to enable MCP OAuth."
            )
            return None

        payload = pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=hydra_audience,
            options={"verify_aud": True},
        )

        subject = payload.get("sub", "")
        if not subject:
            return None

        # Default workspace from ext claims (set during consent) or subject.
        # Any X-Workspace-ID override is validated in the outer dispatcher
        # against accessible_workspaces.
        ext = payload.get("ext", {})
        workspace_id = ext.get("workspace_id") or subject

        return UserContext(
            user_id=subject,
            workspace_id=workspace_id,
        )

    except Exception as e:
        logger.debug(f"Hydra token verification failed: {e}")
        return None


async def get_user_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security_required),
) -> UserContext:
    """FastAPI dependency to extract user context from JWT token (REQUIRED authentication).

    This dependency authenticates the user via JWT token and determines workspace
    from X-Workspace-ID header (falls back to user_id if not provided).

    Raises 401 if authentication fails.

    Args:
        request: FastAPI request object
        credentials: HTTP Bearer token from Authorization header

    Returns:
        UserContext: User and workspace context

    Raises:
        HTTPException: 401 if token is missing or invalid

    Example:
        @router.get("/protected")
        async def protected_endpoint(user: UserContext = Depends(get_user_context)):
            return {"user_id": user.user_id}
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": _www_authenticate_bearer()},
        )

    token = credentials.credentials

    # Check if this is an API key (prefix-based routing)
    if token.startswith(_API_KEY_PREFIX):
        user_context = await _validate_api_key(token, request)
        if user_context is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired API key",
                headers={"WWW-Authenticate": _www_authenticate_bearer()},
            )
        await _resolve_accessible_workspaces(user_context)
        await _apply_workspace_selection(user_context, request)
        ContextManager.set_context(user_context)
        logger.debug(
            f"Authenticated via API key: user={user_context.user_id} workspace={user_context.workspace_id}"
        )
        return user_context

    # Try Kratos JWT first
    auth_provider = get_auth_provider()

    try:
        # Verify token using auth provider
        auth_result: AuthResult = await auth_provider.verify_token(token)

        if not auth_result.is_authenticated or not auth_result.token:
            # Kratos rejected — try Hydra OAuth token before failing
            hydra_context = await _try_hydra_token(token, request)
            if hydra_context is not None:
                await _resolve_accessible_workspaces(hydra_context)
                ContextManager.set_context(hydra_context)
                return hydra_context

            logger.warning(f"Authentication failed: {auth_result.error}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=auth_result.error or "Invalid authentication token",
                headers={"WWW-Authenticate": _www_authenticate_bearer()},
            )

        # Default workspace is the user's personal workspace (= user_id).
        # Any X-Workspace-ID override is validated against accessible_workspaces
        # below — setting a header alone must NEVER grant access.
        user_context = UserContext(
            user_id=auth_result.token.user_id,
            workspace_id=auth_result.token.user_id,
            email=auth_result.token.email,
        )

        # Resolve which workspaces this user can access
        await _resolve_accessible_workspaces(user_context)
        await _apply_workspace_selection(user_context, request)

        # Set context in ContextManager for backward compatibility
        ContextManager.set_context(user_context)

        logger.debug(
            f"Authenticated user: {user_context.user_id} in workspace: {user_context.workspace_id}"
        )

        return user_context

    except HTTPException:
        raise
    except Exception as e:
        # Kratos threw an exception — try Hydra as last resort
        hydra_context = await _try_hydra_token(token, request)
        if hydra_context is not None:
            await _resolve_accessible_workspaces(hydra_context)
            ContextManager.set_context(hydra_context)
            return hydra_context

        logger.error(f"Unexpected error during authentication: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during authentication",
        ) from e


async def resolve_user_context_from_token(
    token: str | None, request: Request
) -> UserContext | None:
    """Resolve a UserContext from a bearer token, or None if absent/invalid.

    This is the single authentication resolution shared by every edge — REST
    optional auth and the A2A protocol both go through it, so an AgentArea API
    key (``aat_``), a Kratos JWT, and a Hydra OAuth token are all accepted the
    same way at every entry point. It never raises for an auth failure; it
    returns None so the caller decides the posture (401, anonymous subject, ...).
    """
    if not token:
        return None

    # API key (prefix-based routing)
    if token.startswith(_API_KEY_PREFIX):
        user_context = await _validate_api_key(token, request)
        if user_context is None:
            logger.debug("API key authentication failed: invalid or expired key")
            return None
        await _resolve_accessible_workspaces(user_context)
        try:
            await _apply_workspace_selection(user_context, request)
        except HTTPException:
            return None
        ContextManager.set_context(user_context)
        return user_context

    # Kratos JWT, with Hydra OAuth token as a fallback (MCP clients).
    auth_provider = get_auth_provider()
    try:
        auth_result: AuthResult = await auth_provider.verify_token(token)

        if not auth_result.is_authenticated or not auth_result.token:
            hydra_context = await _try_hydra_token(token, request)
            if hydra_context is not None:
                await _resolve_accessible_workspaces(hydra_context)
                try:
                    await _apply_workspace_selection(hydra_context, request)
                except HTTPException:
                    return None
                ContextManager.set_context(hydra_context)
                return hydra_context
            logger.debug(f"Token authentication failed: {auth_result.error}")
            return None

        # Default workspace is the user's personal workspace (= user_id).
        # Any X-Workspace-ID override is validated against accessible_workspaces.
        user_context = UserContext(
            user_id=auth_result.token.user_id,
            workspace_id=auth_result.token.user_id,
            email=auth_result.token.email,
        )
        await _resolve_accessible_workspaces(user_context)
        try:
            await _apply_workspace_selection(user_context, request)
        except HTTPException:
            return None
        ContextManager.set_context(user_context)
        return user_context

    except Exception as e:
        hydra_context = await _try_hydra_token(token, request)
        if hydra_context is not None:
            await _resolve_accessible_workspaces(hydra_context)
            ContextManager.set_context(hydra_context)
            return hydra_context
        logger.warning(f"Error during token resolution: {e}")
        return None


async def get_optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security_optional),
) -> UserContext | None:
    """Optionally authenticate user if token is provided (OPTIONAL authentication).

    This dependency allows endpoints to work with or without authentication.
    Returns UserContext if a valid token is provided, None otherwise. Does NOT
    raise 401 if no token provided.

    Example:
        @router.get("/optional")
        async def optional_endpoint(user: Optional[UserContext] = Depends(get_optional_user)):
            if user:
                return {"message": f"Hello {user.user_id}"}
            return {"message": "Hello anonymous user"}
    """
    if not credentials:
        logger.debug("No authentication credentials provided (optional auth)")
        return None

    return await resolve_user_context_from_token(credentials.credentials, request)


async def verify_workspace_access(
    workspace_id: str,
    user: UserContext = Depends(get_user_context),
) -> UserContext:
    """Verify that the authenticated user has access to the specified workspace.

    This dependency can be used when workspace_id is part of the URL path.

    Args:
        workspace_id: Workspace ID from path parameter
        user: Authenticated user context

    Returns:
        UserContext: User context with verified workspace access

    Raises:
        HTTPException: 403 if user doesn't have access to workspace

    Example:
        @router.get("/workspaces/{workspace_id}/agents")
        async def list_agents(
            workspace_id: str,
            user: UserContext = Depends(verify_workspace_access)
        ):
            # user.workspace_id is guaranteed to match workspace_id
            pass
    """
    if user.workspace_id != workspace_id:
        logger.warning(
            f"User {user.user_id} attempted to access workspace {workspace_id} "
            f"but belongs to workspace {user.workspace_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied to workspace {workspace_id}",
        )

    return user


# Type aliases for easier use in endpoint dependencies
UserContextDep = Annotated[UserContext, Depends(get_user_context)]
OptionalUserContextDep = Annotated[UserContext | None, Depends(get_optional_user)]
