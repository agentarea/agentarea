"""Traffic experiments: split runs between the serving revision and a candidate."""

import logging
from uuid import UUID

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.serving.models import AgentExperiment
from agentarea_api.api.deps.services import get_agent_service, get_read_agent_service
from agentarea_common.auth.context import UserContext, UserPrincipal
from agentarea_common.auth.dependencies import UserContextDep, get_principal
from agentarea_common.auth.route_authz import enforced_in_handler
from agentarea_common.config.database import get_db_session
from agentarea_evals.experiments.service import ExperimentError, ExperimentService
from agentarea_evals.runs.service import EvalRunService
from agentarea_evals.schemas import DecisionResponse, ExperimentCreate, ExperimentResponse
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ._serving_common import (
    context_data,
    load_agent,
    require_person_to_widen,
    require_workflow_engine,
    start_workflow,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents/{agent_id}/experiments", tags=["agent-experiments"])

_PER_OBJECT = enforced_in_handler(
    "per-object permission resolved by the PDP once the agent is loaded"
)


def _service(
    session: AsyncSession, user_context: UserContext, agent_service: AgentService
) -> ExperimentService:
    return ExperimentService(
        session,
        user_context,
        activate=agent_service.activate_revision,
        offline_passed=EvalRunService(session, user_context).offline_passed,
    )


async def _response(service: ExperimentService, experiment: AgentExperiment) -> ExperimentResponse:
    control, candidate = await service.arm_stats(experiment)
    return ExperimentResponse.build(
        experiment,
        control=control,
        candidate=candidate,
        offline_passed=await service.offline_gate(experiment),
    )


async def _require(
    service: ExperimentService, agent_id: UUID, experiment_id: UUID
) -> AgentExperiment:
    experiment = await service.get(agent_id, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return experiment


@router.get("", response_model=list[ExperimentResponse], dependencies=[_PER_OBJECT])
async def list_experiments(
    agent_id: str,
    user_context: UserContextDep,
    session: AsyncSession = Depends(get_db_session),
    agent_service: AgentService = Depends(get_read_agent_service),
):
    agent = await load_agent(agent_service, agent_id, user_context, "read")
    service = _service(session, user_context, agent_service)
    return [await _response(service, e) for e in await service.list_for_agent(agent.id)]


@router.post("", response_model=ExperimentResponse, status_code=201, dependencies=[_PER_OBJECT])
async def start_experiment(
    agent_id: str,
    payload: ExperimentCreate,
    user_context: UserContextDep,
    principal: UserPrincipal = Depends(get_principal),
    session: AsyncSession = Depends(get_db_session),
    agent_service: AgentService = Depends(get_agent_service),
):
    """Start splitting runs; the candidate begins at the policy's first step."""
    agent = await load_agent(agent_service, agent_id, user_context, "edit")
    if payload.auto_promote:
        await require_person_to_widen(
            agent_service, agent, payload.candidate_revision_id, principal
        )
    require_workflow_engine()
    service = _service(session, user_context, agent_service)
    try:
        experiment = await service.start(agent, payload.candidate_revision_id, payload.policy())
    except (ExperimentError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    try:
        await start_workflow(
            "ExperimentMonitorWorkflow",
            f"experiment-monitor-{experiment.id}",
            {
                "agent_id": str(agent.id),
                "experiment_id": str(experiment.id),
                "user_context_data": context_data(user_context),
            },
        )
    except Exception as error:
        # An experiment nobody monitors must not split traffic.
        logger.error("experiment %s monitor did not start", experiment.id, exc_info=True)
        await service.stop(experiment, reason="monitor_not_started")
        raise HTTPException(
            status_code=503, detail="The experiment monitor could not start; nothing was routed"
        ) from error
    return await _response(service, experiment)


@router.get("/{experiment_id}", response_model=ExperimentResponse, dependencies=[_PER_OBJECT])
async def get_experiment(
    agent_id: str,
    experiment_id: UUID,
    user_context: UserContextDep,
    session: AsyncSession = Depends(get_db_session),
    agent_service: AgentService = Depends(get_read_agent_service),
):
    agent = await load_agent(agent_service, agent_id, user_context, "read")
    service = _service(session, user_context, agent_service)
    return await _response(service, await _require(service, agent.id, experiment_id))


@router.post(
    "/{experiment_id}/evaluate", response_model=DecisionResponse | None, dependencies=[_PER_OBJECT]
)
async def evaluate_experiment(
    agent_id: str,
    experiment_id: UUID,
    user_context: UserContextDep,
    session: AsyncSession = Depends(get_db_session),
    agent_service: AgentService = Depends(get_agent_service),
):
    """Decide now instead of waiting for the monitor; ``null`` once it has ended."""
    agent = await load_agent(agent_service, agent_id, user_context, "edit")
    service = _service(session, user_context, agent_service)
    decision = await service.evaluate(await _require(service, agent.id, experiment_id))
    return DecisionResponse.build(decision) if decision else None


@router.post("/{experiment_id}/stop", response_model=ExperimentResponse, dependencies=[_PER_OBJECT])
async def stop_experiment(
    agent_id: str,
    experiment_id: UUID,
    user_context: UserContextDep,
    session: AsyncSession = Depends(get_db_session),
    agent_service: AgentService = Depends(get_agent_service),
):
    agent = await load_agent(agent_service, agent_id, user_context, "edit")
    service = _service(session, user_context, agent_service)
    experiment = await _require(service, agent.id, experiment_id)
    try:
        await service.stop(experiment)
    except ExperimentError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return await _response(service, experiment)


@router.post(
    "/{experiment_id}/promote", response_model=ExperimentResponse, dependencies=[_PER_OBJECT]
)
async def promote_experiment(
    agent_id: str,
    experiment_id: UUID,
    user_context: UserContextDep,
    session: AsyncSession = Depends(get_db_session),
    agent_service: AgentService = Depends(get_agent_service),
):
    """Serve the candidate to everyone now."""
    agent = await load_agent(agent_service, agent_id, user_context, "edit")
    service = _service(session, user_context, agent_service)
    experiment = await _require(service, agent.id, experiment_id)
    try:
        await service.promote(experiment)
    except ExperimentError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return await _response(service, experiment)
