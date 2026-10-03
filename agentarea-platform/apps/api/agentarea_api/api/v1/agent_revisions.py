"""Agent revisions: history, diff, candidates and activation (promotion or rollback)."""

from uuid import UUID

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.serving.revision_service import (
    RevisionNotFoundError,
    StaleRevisionError,
    UnchangedRevisionError,
)
from agentarea_agents.serving.revision_spec import RevisionSpec, diff_specs
from agentarea_api.api.deps.services import get_agent_service, get_read_agent_service
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.route_authz import enforced_in_handler
from agentarea_common.config.database import get_db_session
from agentarea_common.exceptions.errors import NotFoundError
from agentarea_evals.outcomes.stats import OutcomeStats
from agentarea_evals.schemas import (
    FieldChange,
    RevisionCreate,
    RevisionOutcomeResponse,
    RevisionResponse,
)
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ._serving_common import load_agent

router = APIRouter(prefix="/agents/{agent_id}/revisions", tags=["agent-revisions"])

_PER_OBJECT = enforced_in_handler(
    "per-object permission resolved by the PDP once the agent is loaded"
)


@router.get("", response_model=list[RevisionResponse], dependencies=[_PER_OBJECT])
async def list_revisions(
    agent_id: str,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_read_agent_service),
):
    """Every revision of the agent, newest first."""
    agent = await load_agent(agent_service, agent_id, user_context, "read")
    revisions = await agent_service.revisions().list_revisions(agent.id)
    return [RevisionResponse.build(r, current_id=agent.current_revision_id) for r in revisions]


@router.get("/outcomes", response_model=list[RevisionOutcomeResponse], dependencies=[_PER_OBJECT])
async def revision_outcomes(
    agent_id: str,
    user_context: UserContextDep,
    session: AsyncSession = Depends(get_db_session),
    agent_service: AgentService = Depends(get_read_agent_service),
):
    """Outcomes of past runs per revision. Observational: revisions saw different inputs."""
    agent = await load_agent(agent_service, agent_id, user_context, "read")
    numbers = {r.id: r.number for r in await agent_service.revisions().list_revisions(agent.id)}
    outcomes = await OutcomeStats(session, user_context).by_revision(agent.id)
    return sorted(
        (RevisionOutcomeResponse.build(o, numbers.get(o.revision_id)) for o in outcomes),
        key=lambda o: -(o.number or 0),
    )


@router.get("/{revision_id}", response_model=RevisionResponse, dependencies=[_PER_OBJECT])
async def get_revision(
    agent_id: str,
    revision_id: UUID,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_read_agent_service),
):
    agent = await load_agent(agent_service, agent_id, user_context, "read")
    revision = await agent_service.revisions().get(agent.id, revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="Revision not found")
    return RevisionResponse.build(revision, current_id=agent.current_revision_id)


@router.get("/{revision_id}/diff", response_model=list[FieldChange], dependencies=[_PER_OBJECT])
async def diff_revision(
    agent_id: str,
    revision_id: UUID,
    user_context: UserContextDep,
    against: UUID | None = Query(default=None, description="Defaults to the serving revision"),
    agent_service: AgentService = Depends(get_read_agent_service),
):
    """What changes going from ``against`` (the serving revision by default) to this one."""
    agent = await load_agent(agent_service, agent_id, user_context, "read")
    revisions = agent_service.revisions()
    target = await revisions.get(agent.id, revision_id)
    base_id = against or agent.current_revision_id
    base = await revisions.get(agent.id, base_id) if base_id else None
    if target is None or base is None:
        raise HTTPException(status_code=404, detail="Revision not found")
    return [
        FieldChange(**change)
        for change in diff_specs(
            RevisionSpec.from_dict(base.spec), RevisionSpec.from_dict(target.spec)
        )
    ]


@router.post("", response_model=RevisionResponse, status_code=201, dependencies=[_PER_OBJECT])
async def create_candidate(
    agent_id: str,
    payload: RevisionCreate,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_agent_service),
):
    """Propose a candidate revision. What serves does not change until it is activated."""
    agent = await load_agent(agent_service, agent_id, user_context, "edit")
    try:
        revision = await agent_service.propose_revision(
            agent.id,
            payload.patch(),
            message=payload.message,
            rationale=payload.rationale,
            evidence=payload.evidence,
            origin="user",
        )
    except UnchangedRevisionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RevisionResponse.build(revision, current_id=agent.current_revision_id)


@router.post("/{revision_id}/activate", response_model=RevisionResponse, dependencies=[_PER_OBJECT])
async def activate_revision(
    agent_id: str,
    revision_id: UUID,
    user_context: UserContextDep,
    agent_service: AgentService = Depends(get_agent_service),
):
    """Serve this revision: promote a candidate, or roll back to an earlier one."""
    agent = await load_agent(agent_service, agent_id, user_context, "edit")
    try:
        revision = await agent_service.activate_revision(agent.id, revision_id)
    except (RevisionNotFoundError, NotFoundError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except StaleRevisionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return RevisionResponse.build(revision, current_id=revision.id)
