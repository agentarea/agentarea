"""A2A Protocol Authentication and Authorization.

This module provides authentication and authorization middleware for A2A protocol endpoints.
Supports multiple authentication schemes as specified in the A2A protocol.
"""

import logging
from typing import Any, ClassVar
from uuid import UUID

from agentarea_agents.application.agent_service import AgentService
from agentarea_api.api.deps.services import get_agent_service
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_optional_user
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


def _a2a_metadata(request: Request, **extra: str | None) -> dict[str, Any]:
    """Request metadata carried on the A2A auth context."""
    return {
        "user_agent": request.headers.get("user-agent"),
        "client_ip": request.client.host if request.client else None,
        **{k: v for k, v in extra.items() if v is not None},
    }


async def require_a2a_auth(
    request: Request,
    agent_id: UUID,
    permission: str = A2APermissions.AGENT_READ,
    agent_service: AgentService = Depends(get_agent_service),
    subject: UserContext | None = Depends(get_optional_user),
) -> A2AAuthContext:
    """Authenticate + authorize an A2A request through the shared edge policy.

    A2A carries no auth or permission model of its own (ADR-006). The subject
    is resolved by the SAME dependency every optional-auth REST endpoint uses
    (``get_optional_user`` → the shared ``HTTPBearer`` scheme, handling Kratos
    JWT + ``aat_`` API key + Hydra OAuth), and the allow/deny decision is made
    by the single edge authorizer (``authorize_agent_action``). An ``aat_`` key
    that works over REST works here too; a public-execution grant is honored
    without a key.
    """
    from agentarea_common.auth.access import authorize_agent_action

    agent = await agent_service.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    decision = await authorize_agent_action(
        subject,
        permission,
        agent_workspace_id=str(agent.workspace_id),
        agent_id=str(agent_id),
    )
    if not decision.allowed:
        if subject is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        logger.warning(
            f"A2A authorization denied: user={subject.user_id}, "
            f"agent={agent_id}, required={permission}, reason={decision.reason}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient permissions. Required: {permission}",
        )

    return A2AAuthContext(
        authenticated=subject is not None,
        user_id=subject.user_id if subject else None,
        workspace_id=str(subject.workspace_id) if subject else str(agent.workspace_id),
        agent_id=agent_id,
        permissions=[permission],
        auth_method="bearer" if subject else "anonymous",
        metadata=_a2a_metadata(request, agent_name=agent.name, agent_status=agent.status),
    )


async def require_a2a_write_auth(
    request: Request,
    agent_id: UUID,
    agent_service: AgentService = Depends(get_agent_service),
    subject: UserContext | None = Depends(get_optional_user),
) -> A2AAuthContext:
    """Require A2A write permission."""
    return await require_a2a_auth(
        request, agent_id, A2APermissions.AGENT_WRITE, agent_service, subject
    )


async def require_a2a_execute_auth(
    request: Request,
    agent_id: UUID,
    agent_service: AgentService = Depends(get_agent_service),
    subject: UserContext | None = Depends(get_optional_user),
) -> A2AAuthContext:
    """Require A2A execute permission."""
    return await require_a2a_auth(
        request, agent_id, A2APermissions.AGENT_EXECUTE, agent_service, subject
    )


async def require_a2a_stream_auth(
    request: Request,
    agent_id: UUID,
    agent_service: AgentService = Depends(get_agent_service),
    subject: UserContext | None = Depends(get_optional_user),
) -> A2AAuthContext:
    """Require A2A stream permission."""
    return await require_a2a_auth(
        request, agent_id, A2APermissions.AGENT_STREAM, agent_service, subject
    )


async def allow_public_access(
    request: Request,
    subject: UserContext | None = Depends(get_optional_user),
) -> A2AAuthContext:
    """Public discovery endpoints: resolve the subject if a token is present,
    but require no permission. Uses the same shared resolver — no bespoke auth.
    """
    return A2AAuthContext(
        authenticated=subject is not None,
        user_id=subject.user_id if subject else None,
        workspace_id=str(subject.workspace_id) if subject else None,
        permissions=[A2APermissions.AGENT_READ],
        auth_method="bearer" if subject else "anonymous",
        metadata=_a2a_metadata(request),
    )
