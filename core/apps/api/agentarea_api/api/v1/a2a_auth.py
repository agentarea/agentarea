"""A2A Protocol Authentication and Authorization.

This module provides authentication and authorization middleware for A2A protocol endpoints.
Supports multiple authentication schemes as specified in the A2A protocol.
"""

import logging
from typing import Any, ClassVar
from uuid import UUID

from agentarea_agents.application.agent_service import AgentService
from agentarea_api.api.deps.services import get_agent_service
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Security schemes
bearer_scheme = HTTPBearer(auto_error=False)


class A2AAuthContext(BaseModel):
    """A2A authentication context with workspace support."""

    authenticated: bool
    user_id: str | None = None
    workspace_id: str | None = None
    agent_id: UUID | None = None
    permissions: list[str] = []
    auth_method: str | None = None
    metadata: dict[str, Any] = {}


class A2APermissions:
    """A2A protocol permissions."""

    AGENT_READ = "agent:read"
    AGENT_WRITE = "agent:write"
    AGENT_EXECUTE = "agent:execute"
    AGENT_STREAM = "agent:stream"
    AGENT_ADMIN = "agent:admin"

    # Default permissions for different roles
    PUBLIC_PERMISSIONS: ClassVar[list[str]] = [AGENT_READ]
    USER_PERMISSIONS: ClassVar[list[str]] = [
        AGENT_READ,
        AGENT_WRITE,
        AGENT_EXECUTE,
        AGENT_STREAM,
    ]
    ADMIN_PERMISSIONS: ClassVar[list[str]] = [
        AGENT_READ,
        AGENT_WRITE,
        AGENT_EXECUTE,
        AGENT_STREAM,
        AGENT_ADMIN,
    ]


async def extract_auth_from_request(request: Request) -> dict[str, Any]:
    """Extract authentication information from request."""
    auth_info = {"method": None, "credentials": None, "metadata": {}}

    # Check Authorization header (Bearer token)
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        auth_info["method"] = "bearer"
        auth_info["credentials"] = auth_header[7:]  # Remove "Bearer " prefix

    # Check API Key header
    api_key = request.headers.get("x-api-key")
    if api_key:
        auth_info["method"] = "api_key"
        auth_info["credentials"] = api_key

    # Extract additional metadata
    auth_info["metadata"] = {
        "user_agent": request.headers.get("user-agent"),
        "client_ip": request.client.host if request.client else None,
        "forwarded_for": request.headers.get("x-forwarded-for"),
    }

    return auth_info


async def authenticate_bearer_token(token: str) -> dict[str, Any] | None:
    """Authenticate bearer token using Kratos auth provider."""
    from agentarea_common.auth.providers.factory import AuthProviderFactory
    from agentarea_common.config.app import get_app_settings

    try:
        settings = get_app_settings()
        auth_provider = AuthProviderFactory.create_provider(
            "kratos",
            config={
                "jwks_b64": settings.KRATOS_JWKS_B64,
                "issuer": settings.KRATOS_ISSUER,
                "audience": settings.KRATOS_AUDIENCE,
            },
        )

        # Verify token using Kratos provider
        auth_result = await auth_provider.verify_token(token)

        if not auth_result.is_authenticated or not auth_result.token:
            logger.warning(f"Bearer token authentication failed: {auth_result.error}")
            return None

        # Extract user information from validated token
        return {
            "user_id": auth_result.token.user_id,
            "workspace_id": "default",  # TODO: Extract from token or user metadata
            "permissions": A2APermissions.USER_PERMISSIONS,
            "valid": True,
        }

    except Exception as e:
        logger.error(f"Error authenticating bearer token: {e}")
        return None


async def authenticate_api_key(api_key: str) -> dict[str, Any] | None:
    """Authenticate API key and extract user context including workspace.

    TODO: Implement proper API key authentication with database lookup.
    API keys should be stored hashed in the database with associated user/workspace context.
    """
    # API key authentication not yet implemented
    logger.warning("API key authentication attempted but not yet implemented")
    return None


async def get_a2a_auth_context(
    request: Request, agent_id: UUID | None = None, required_permission: str | None = None
) -> A2AAuthContext:
    """Get A2A authentication context for request."""
    # Extract authentication info
    auth_info = await extract_auth_from_request(request)

    # Initialize context with defaults
    context = A2AAuthContext(
        authenticated=False,
        permissions=A2APermissions.PUBLIC_PERMISSIONS,
        metadata=auth_info["metadata"],
    )

    # Authenticate based on method
    auth_result = None

    if auth_info["method"] == "bearer" and auth_info["credentials"]:
        auth_result = await authenticate_bearer_token(auth_info["credentials"])
        context.auth_method = "bearer"
    elif auth_info["method"] == "api_key" and auth_info["credentials"]:
        auth_result = await authenticate_api_key(auth_info["credentials"])
        context.auth_method = "api_key"

    # Update context if authenticated
    if auth_result and auth_result.get("valid"):
        context.authenticated = True
        context.user_id = auth_result["user_id"]
        context.workspace_id = auth_result.get("workspace_id", "default")
        context.permissions = auth_result["permissions"]
        context.agent_id = agent_id

        logger.info(
            f"A2A authentication successful: user={context.user_id}, workspace={context.workspace_id}, method={context.auth_method}"
        )
    else:
        logger.info(f"A2A authentication failed or not provided: method={auth_info['method']}")

    # Check required permission
    if required_permission and required_permission not in context.permissions:
        logger.warning(
            f"A2A authorization failed: user={context.user_id}, required={required_permission}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient permissions. Required: {required_permission}",
        )

    return context


async def require_a2a_auth(
    request: Request,
    agent_id: UUID,
    permission: str = A2APermissions.AGENT_READ,
    agent_service: AgentService = Depends(get_agent_service),
) -> A2AAuthContext:
    """Require A2A authentication with specific permission."""
    # Verify agent exists
    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Get auth context with required permission
    context = await get_a2a_auth_context(request, agent_id, permission)

    # Ensure user is authenticated
    if not context.authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Add agent info to context
    context.metadata["agent_name"] = agent.name
    context.metadata["agent_status"] = agent.status

    return context


async def require_a2a_write_auth(
    request: Request, agent_id: UUID, agent_service: AgentService = Depends(get_agent_service)
) -> A2AAuthContext:
    """Require A2A write permission."""
    return await require_a2a_auth(request, agent_id, A2APermissions.AGENT_WRITE, agent_service)


async def require_a2a_execute_auth(
    request: Request, agent_id: UUID, agent_service: AgentService = Depends(get_agent_service)
) -> A2AAuthContext:
    """Require A2A execute permission."""
    return await require_a2a_auth(request, agent_id, A2APermissions.AGENT_EXECUTE, agent_service)


async def require_a2a_stream_auth(
    request: Request, agent_id: UUID, agent_service: AgentService = Depends(get_agent_service)
) -> A2AAuthContext:
    """Require A2A stream permission."""
    return await require_a2a_auth(request, agent_id, A2APermissions.AGENT_STREAM, agent_service)


# Public dependency - no auth required
async def allow_public_access(request: Request) -> A2AAuthContext:
    """Allow public access (for discovery endpoints)."""
    return await get_a2a_auth_context(request)
