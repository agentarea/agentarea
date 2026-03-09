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

from .context import UserContext
from .context_manager import ContextManager
from .interfaces import AuthResult
from .providers.factory import AuthProviderFactory

logger = logging.getLogger(__name__)

_API_KEY_PREFIX = "aat_"

# Security schemes
# Required authentication - raises 401 if no token
security_required = HTTPBearer()

# Optional authentication - returns None if no token (doesn't raise error)
security_optional = HTTPBearer(auto_error=False)


async def _validate_api_key(token: str, request: Request) -> UserContext | None:
    """Validate an API key and return UserContext, or None if invalid."""
    from agentarea_mcp.domain.auth_models import MCPAccessToken
    from sqlalchemy import select
    from sqlalchemy import update as sa_update

    from agentarea_common.config import get_database

    token_hash = hashlib.sha256(token.encode()).hexdigest()

    async with get_database().async_session_factory() as session:
        result = await session.execute(
            select(MCPAccessToken).where(MCPAccessToken.token_hash == token_hash)
        )
        record = result.scalar_one_or_none()

        if record is None or not record.is_active:
            return None
        if record.expires_at and datetime.utcnow() >= record.expires_at:
            return None

        # Increment access count (best-effort)
        try:
            await session.execute(
                sa_update(MCPAccessToken)
                .where(MCPAccessToken.id == record.id)
                .values(
                    access_count=MCPAccessToken.access_count + 1,
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
    from agentarea_common.config.app import get_app_settings

    settings = get_app_settings()

    return AuthProviderFactory.create_provider(
        "kratos",
        config={
            "jwks_b64": settings.KRATOS_JWKS_B64,
            "issuer": settings.KRATOS_ISSUER,
            "audience": settings.KRATOS_AUDIENCE,
        },
    )


async def get_user_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security_required),
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
    token = credentials.credentials

    # Check if this is an API key (prefix-based routing)
    if token.startswith(_API_KEY_PREFIX):
        user_context = await _validate_api_key(token, request)
        if user_context is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired API key",
                headers={"WWW-Authenticate": "Bearer"},
            )
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
            logger.warning(f"Authentication failed: {auth_result.error}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=auth_result.error or "Invalid authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Get workspace from header, fallback to user_id
        workspace_id = request.headers.get("X-Workspace-ID") or auth_result.token.user_id

        # Create user context
        user_context = UserContext(
            user_id=auth_result.token.user_id,
            workspace_id=workspace_id,
            roles=[],  # TODO: Extract roles from token or database
        )

        # Set context in ContextManager for backward compatibility
        ContextManager.set_context(user_context)

        logger.debug(
            f"Authenticated user: {user_context.user_id} in workspace: {user_context.workspace_id}"
        )

        return user_context

    except HTTPException:
        raise
    except Exception as e:
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
