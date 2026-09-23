"""Read-only, current-workspace human-to-agent invocation access inspection."""

import logging
from typing import Annotated, Literal

from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_common.auth import UserContext, UserContextDep, assert_workspace_admin
from agentarea_common.auth.access import AGENT_EXECUTE, authorize_agent_action
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.config.database import get_db_session
from agentarea_common.rebac import (
    KetoError,
    KetoUnavailableError,
    OpenFGAError,
    OpenFGAUnavailableError,
)
from agentarea_common.workspaces.memberships import (
    get_workspace_membership_graph,
    list_workspace_member_ids,
)
from agentarea_common.workspaces.models import Workspace
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
router = APIRouter()
DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
_MAX_PEOPLE = 100
_MAX_AGENTS = 100


class NetworkPerson(BaseModel):
    user_id: str
    display_name: str | None = None
    email: str | None = None


class NetworkPersonAgentAccess(BaseModel):
    user_id: str
    agent_id: str
    allowed: bool
    reason: str


class NetworkPeopleAccessResponse(BaseModel):
    workspace_id: str
    people: list[NetworkPerson]
    access: list[NetworkPersonAgentAccess]
    complete: bool
    total_people: int | None = Field(ge=0)
    total_agents: int = Field(ge=0)
    decision_source: Literal["agent_edge_admission"] = "agent_edge_admission"
    directory_status: Literal["available", "disabled"] = "available"


@router.get("/people-access", response_model=NetworkPeopleAccessResponse)
async def get_network_people_access(
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> NetworkPeopleAccessResponse:
    """Inspect current-workspace people's ``agent:execute`` admission.

    Uses the existing workspace-management authorization gate. Membership and
    ownership establish evaluation subjects; this never acts as those users.
    At most 100 people and 100 agents are evaluated, with ``complete=False``
    when either list is truncated. Results assume an authenticated participant
    and do not represent the restrictions of a particular token or task.

    An intentionally disabled membership directory exposes only the persisted
    workspace owner, with ``directory_status=disabled``, ``total_people=None``
    and ``complete=False``. An enabled directory that fails still returns 503.
    """
    await assert_workspace_admin(user_context)
    workspace_id = user_context.workspace_id
    try:
        graph = get_workspace_membership_graph()
        member_ids: set[str] = set()
        if graph is not None:
            member_ids.update(await list_workspace_member_ids(graph, workspace_id))
    except (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError) as exc:
        logger.exception("Failed to inspect network workspace memberships")
        raise HTTPException(
            status_code=503, detail="Workspace membership graph unavailable"
        ) from exc

    owner_query = select(Workspace.owner_user_id).where(Workspace.id == workspace_id)
    owner_id = (await db_session.execute(owner_query)).scalar_one_or_none()
    if owner_id:
        member_ids.add(owner_id)
    selected_ids = sorted(member_ids)[:_MAX_PEOPLE]
    if owner_id and owner_id not in selected_ids:
        selected_ids = sorted([*selected_ids[: _MAX_PEOPLE - 1], owner_id])

    factory = RepositoryFactory(db_session, user_context)
    agent_repository = factory.create_repository(AgentRepository)
    agents = sorted(
        await agent_repository.list_all(workspace_id=workspace_id),
        key=lambda agent: str(agent.id),
    )
    selected_agents = agents[:_MAX_AGENTS]
    people = [
        NetworkPerson(
            user_id=user_id,
            email=user_context.email if user_id == user_context.user_id else None,
        )
        for user_id in selected_ids
    ]
    access: list[NetworkPersonAgentAccess] = []
    for person in people:
        # Only graph membership or persisted ownership can create this evaluation
        # subject. Repository reads continue to use the authenticated actor above.
        subject = UserContext(
            user_id=person.user_id,
            workspace_id=workspace_id,
            accessible_workspaces=[workspace_id],
        )
        for agent in selected_agents:
            decision = await authorize_agent_action(
                subject,
                AGENT_EXECUTE,
                agent_workspace_id=str(agent.workspace_id),
                agent_id=str(agent.id),
            )
            access.append(
                NetworkPersonAgentAccess(
                    user_id=person.user_id,
                    agent_id=str(agent.id),
                    allowed=decision.allowed,
                    reason=decision.reason,
                )
            )

    return NetworkPeopleAccessResponse(
        workspace_id=workspace_id,
        people=people,
        access=access,
        complete=graph is not None
        and len(selected_ids) == len(member_ids)
        and len(selected_agents) == len(agents),
        total_people=len(member_ids) if graph is not None else None,
        total_agents=len(agents),
        directory_status="available" if graph is not None else "disabled",
    )
