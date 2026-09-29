"""A2A Protocol Authentication and Authorization.

This module provides authentication and authorization middleware for A2A protocol endpoints.
Supports multiple authentication schemes as specified in the A2A protocol.
"""

import logging
from typing import Any, ClassVar
from uuid import UUID

from agentarea_agents.domain.models import Agent
from agentarea_api.api.v1 import agents_well_known
from agentarea_common.auth.context import UserPrincipal
from agentarea_common.auth.dependencies import (
    bind_request_workspace,
    binds_workspace,
    get_optional_principal,
)
from agentarea_common.config.database import get_read_db_session
from agentarea_common.workspaces.lookup import workspace_slug_for
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Security schemes
bearer_scheme = HTTPBearer(auto_error=False)


class A2AAuthContext(BaseModel):
    """A2A authentication context with workspace support."""

    authenticated: bool
    user_id: str | None = None
    workspace_id: str | None = None
    workspace_slug: str | None = None
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


async def load_a2a_agent(
    agent_id: str,
    db_session: AsyncSession = Depends(get_read_db_session),
) -> Agent:
    """The agent the A2A URL names, looked up across workspaces.

    Unscoped on purpose: the URL names no workspace, and the caller's
    authority over the agent's workspace is decided afterwards by the edge
    authorizer, not by which workspace the lookup happened to run in. A
    malformed id is parsed here and answers like a missing agent: left to
    FastAPI, the validation error would not stop the dependencies after this
    one, which would find no workspace bound and fail as a server error.
    """
    try:
        agent_uuid = UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Agent not found") from None
    agent = await agents_well_known.get_public_agent(agent_uuid, db_session)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def require_a2a_auth(
    request: Request,
    agent_id: UUID,
    permission: str,
    agent: Agent,
    subject: UserPrincipal | None,
) -> A2AAuthContext:
    """Authenticate + authorize an A2A request, then act in the agent's workspace.

    A2A carries no auth or permission model of its own (ADR-006). The subject
    is resolved by the SAME resolver every optional-auth edge uses
    (``get_optional_principal`` → the shared ``HTTPBearer`` scheme, handling
    Kratos JWT + ``aat_`` API key + Hydra OAuth), and the allow/deny decision is
    made by the single edge authorizer (``authorize_agent_action``) against the
    agent's workspace. On success that workspace is bound for the request, so
    every workspace-scoped dependency the handler builds is scoped to where the
    agent lives rather than to wherever the caller was acting.
    """
    from agentarea_common.auth.access import authorize_agent_action

    agent_workspace_id = str(agent.workspace_id)
    decision = await authorize_agent_action(
        subject,
        permission,
        agent_workspace_id=agent_workspace_id,
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

    workspace_slug = await workspace_slug_for(agent_workspace_id)
    bind_request_workspace(request, agent_workspace_id, workspace_slug)
    return A2AAuthContext(
        authenticated=subject is not None,
        user_id=subject.user_id if subject else None,
        workspace_id=agent_workspace_id,
        workspace_slug=workspace_slug,
        agent_id=agent_id,
        permissions=[permission],
        auth_method="bearer" if subject else "anonymous",
        metadata=_a2a_metadata(request, agent_name=agent.name, agent_status=agent.status),
    )


@binds_workspace
async def require_a2a_read_auth(
    request: Request,
    agent_id: UUID,
    agent: Agent = Depends(load_a2a_agent),
    subject: UserPrincipal | None = Depends(get_optional_principal),
) -> A2AAuthContext:
    """Require A2A read permission."""
    return await require_a2a_auth(request, agent_id, A2APermissions.AGENT_READ, agent, subject)


@binds_workspace
async def require_a2a_write_auth(
    request: Request,
    agent_id: UUID,
    agent: Agent = Depends(load_a2a_agent),
    subject: UserPrincipal | None = Depends(get_optional_principal),
) -> A2AAuthContext:
    """Require A2A write permission."""
    return await require_a2a_auth(request, agent_id, A2APermissions.AGENT_WRITE, agent, subject)


@binds_workspace
async def require_a2a_execute_auth(
    request: Request,
    agent_id: UUID,
    agent: Agent = Depends(load_a2a_agent),
    subject: UserPrincipal | None = Depends(get_optional_principal),
) -> A2AAuthContext:
    """Require A2A execute permission."""
    return await require_a2a_auth(request, agent_id, A2APermissions.AGENT_EXECUTE, agent, subject)


@binds_workspace
async def require_a2a_stream_auth(
    request: Request,
    agent_id: UUID,
    agent: Agent = Depends(load_a2a_agent),
    subject: UserPrincipal | None = Depends(get_optional_principal),
) -> A2AAuthContext:
    """Require A2A stream permission."""
    return await require_a2a_auth(request, agent_id, A2APermissions.AGENT_STREAM, agent, subject)


async def allow_public_access(
    request: Request,
    subject: UserPrincipal | None = Depends(get_optional_principal),
) -> A2AAuthContext:
    """Public discovery endpoints: resolve the subject if a token is present,
    but require no permission. Uses the same shared resolver — no bespoke auth.
    """
    return A2AAuthContext(
        authenticated=subject is not None,
        user_id=subject.user_id if subject else None,
        permissions=[A2APermissions.AGENT_READ],
        auth_method="bearer" if subject else "anonymous",
        metadata=_a2a_metadata(request),
    )
