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
    """Populate accessible_workspaces on UserContext via AuthorizationService."""
    from agentarea_common.di.container import resolve

    authz = resolve(AuthorizationService)
    user_context.accessible_workspaces = await authz.get_accessible_workspaces(user_context)


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

        # workspace_id from header takes precedence, fallback to record's workspace
        workspace_id = request.headers.get("X-Workspace-ID") or str(record.workspace_id)

        return UserContext(
            user_id=str(record.created_by),
            workspace_id=workspace_id,
            roles=[],
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

    try:
        jwks_client = _get_hydra_jwks()
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        payload = pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )

        subject = payload.get("sub", "")
        if not subject:
            return None

        # workspace_id from token ext claims (set during consent) or header or subject
        ext = payload.get("ext", {})
        workspace_id = request.headers.get("X-Workspace-ID") or ext.get("workspace_id") or subject

        return UserContext(
            user_id=subject,
            workspace_id=workspace_id,
            roles=[],
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

        # Get workspace from header, fallback to user_id
        workspace_id = request.headers.get("X-Workspace-ID") or auth_result.token.user_id

        # Create user context
        user_context = UserContext(
            user_id=auth_result.token.user_id,
            workspace_id=workspace_id,
            roles=[],  # TODO: Extract roles from token or database
        )

        # Resolve which workspaces this user can access
        await _resolve_accessible_workspaces(user_context)

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


async def get_optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security_optional),
) -> UserContext | None:
    """Optionally authenticate user if token is provided (OPTIONAL authentication).

    This dependency allows endpoints to work with or without authentication.
    Returns UserContext if a valid token is provided, None otherwise.

    Does NOT raise 401 if no token provided.

    Args:
        request: FastAPI request object
        credentials: Optional HTTP Bearer token from Authorization header

    Returns:
        Optional[UserContext]: User context if authenticated, None otherwise

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

    token = credentials.credentials

    # Check if this is an API key (prefix-based routing)
    if token.startswith(_API_KEY_PREFIX):
        user_context = await _validate_api_key(token, request)
        if user_context is None:
            logger.debug("Optional API key authentication failed: invalid or expired key")
            return None
        await _resolve_accessible_workspaces(user_context)
        ContextManager.set_context(user_context)
        logger.debug(
            f"Authenticated via API key: user={user_context.user_id} workspace={user_context.workspace_id}"
        )
        return user_context

    # Otherwise, verify as JWT
    auth_provider = get_auth_provider()

    try:
        # Verify token using auth provider
        auth_result: AuthResult = await auth_provider.verify_token(token)

        if not auth_result.is_authenticated or not auth_result.token:
            logger.debug(f"Optional authentication failed: {auth_result.error}")
            return None

        # Get workspace from header, fallback to user_id
        workspace_id = request.headers.get("X-Workspace-ID") or auth_result.token.user_id

        # Create user context
        user_context = UserContext(
            user_id=auth_result.token.user_id,
            workspace_id=workspace_id,
            roles=[],
        )

        # Resolve accessible workspaces
        await _resolve_accessible_workspaces(user_context)

        # Set context in ContextManager
        ContextManager.set_context(user_context)

        logger.debug(f"Optionally authenticated user: {user_context.user_id}")

        return user_context

    except Exception as e:
        logger.warning(f"Error during optional authentication: {e}")
        return None


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
