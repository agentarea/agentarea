"""Evaluation suites and cases (workspace resources) and suite runs against an agent."""

from uuid import UUID

from agentarea_agents.application.agent_service import AgentService
from agentarea_api.api.deps.services import get_agent_service, get_read_agent_service
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.route_authz import enforced_in_handler, unrestricted
from agentarea_common.config.database import get_db_session
from agentarea_evals.runs.service import EvalRunError, EvalRunService
from agentarea_evals.schemas import (
    CaseCreate,
    CaseFromTask,
    CaseResponse,
    EvalRunCreate,
    EvalRunDetail,
    EvalRunResponse,
    EvalTrialResponse,
    SuiteCreate,
    SuiteResponse,
)
from agentarea_evals.suites.service import SuiteError, SuiteService
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ._serving_common import context_data, load_agent, start_workflow

suites_router = APIRouter(prefix="/eval-suites", tags=["evals"])
runs_router = APIRouter(prefix="/agents/{agent_id}/eval-runs", tags=["evals"])

_MEMBER = unrestricted("workspace member; the workspace-scoped repository is the boundary")
_PER_OBJECT = enforced_in_handler(
    "per-object permission resolved by the PDP once the agent is loaded"
)


def _suite_error(error: Exception) -> HTTPException:
    message = str(error)
    return HTTPException(status_code=404 if "not found" in message else 422, detail=message)


@suites_router.get("", response_model=list[SuiteResponse], dependencies=[_MEMBER])
async def list_suites(
    user_context: UserContextDep, session: AsyncSession = Depends(get_db_session)
):
    suites = SuiteService(session, user_context)
    return [
        SuiteResponse.build(suite, len(await suites.list_cases(suite.id)))
        for suite in await suites.list_suites()
    ]


@suites_router.post("", response_model=SuiteResponse, status_code=201, dependencies=[_MEMBER])
async def create_suite(
    payload: SuiteCreate,
    user_context: UserContextDep,
    session: AsyncSession = Depends(get_db_session),
):
    suite = await SuiteService(session, user_context).create_suite(
        payload.name, payload.description
    )
    return SuiteResponse.build(suite, 0)


@suites_router.get("/{suite_id}", response_model=SuiteResponse, dependencies=[_MEMBER])
async def get_suite(
    suite_id: UUID, user_context: UserContextDep, session: AsyncSession = Depends(get_db_session)
):
    suites = SuiteService(session, user_context)
    suite = await suites.get_suite(suite_id)
    if suite is None:
        raise HTTPException(status_code=404, detail="Suite not found")
    return SuiteResponse.build(suite, len(await suites.list_cases(suite.id)))


@suites_router.patch("/{suite_id}", response_model=SuiteResponse, dependencies=[_MEMBER])
async def update_suite(
    suite_id: UUID,
    payload: SuiteCreate,
    user_context: UserContextDep,
    session: AsyncSession = Depends(get_db_session),
):
    suites = SuiteService(session, user_context)
    try:
        suite = await suites.update_suite(
            suite_id, name=payload.name, description=payload.description
        )
    except SuiteError as error:
        raise _suite_error(error) from error
    return SuiteResponse.build(suite, len(await suites.list_cases(suite.id)))


@suites_router.delete("/{suite_id}", status_code=204, dependencies=[_MEMBER])
async def delete_suite(
    suite_id: UUID, user_context: UserContextDep, session: AsyncSession = Depends(get_db_session)
):
    try:
        await SuiteService(session, user_context).delete_suite(suite_id)
    except SuiteError as error:
        raise _suite_error(error) from error
    return Response(status_code=204)


@suites_router.get("/{suite_id}/cases", response_model=list[CaseResponse], dependencies=[_MEMBER])
async def list_cases(
    suite_id: UUID, user_context: UserContextDep, session: AsyncSession = Depends(get_db_session)
):
    suites = SuiteService(session, user_context)
    if await suites.get_suite(suite_id) is None:
        raise HTTPException(status_code=404, detail="Suite not found")
    return [CaseResponse.build(case) for case in await suites.list_cases(suite_id)]


@suites_router.post(
    "/{suite_id}/cases", response_model=CaseResponse, status_code=201, dependencies=[_MEMBER]
)
async def add_case(
    suite_id: UUID,
    payload: CaseCreate,
    user_context: UserContextDep,
    session: AsyncSession = Depends(get_db_session),
):
    try:
        case = await SuiteService(session, user_context).add_case(
            suite_id,
            name=payload.name,
            input=payload.input,
            parameters=payload.parameters,
            checks=payload.checks,
            stubs=payload.stubs,
        )
    except ValueError as error:
        raise _suite_error(error) from error
    return CaseResponse.build(case)


@suites_router.post(
    "/{suite_id}/cases/from-task",
    response_model=CaseResponse,
    status_code=201,
    dependencies=[_MEMBER],
)
async def add_case_from_task(
    suite_id: UUID,
    payload: CaseFromTask,
    user_context: UserContextDep,
    session: AsyncSession = Depends(get_db_session),
):
    """A case from a real run: its input, and draft stubs from the tool answers it got."""
    try:
        case = await SuiteService(session, user_context).case_from_task(
            suite_id, payload.task_id, name=payload.name
        )
    except ValueError as error:
        raise _suite_error(error) from error
    return CaseResponse.build(case)


@suites_router.patch(
    "/{suite_id}/cases/{case_id}", response_model=CaseResponse, dependencies=[_MEMBER]
)
async def update_case(
    suite_id: UUID,
    case_id: UUID,
    payload: CaseCreate,
    user_context: UserContextDep,
    session: AsyncSession = Depends(get_db_session),
):
    suites = SuiteService(session, user_context)
    existing = await suites.get_case(case_id)
    if existing is None or existing.suite_id != suite_id:
        raise HTTPException(status_code=404, detail="Case not found")
    try:
        case = await suites.update_case(
            case_id,
            name=payload.name,
            input=payload.input,
            parameters=payload.parameters,
            checks=payload.checks,
            stubs=payload.stubs,
        )
    except ValueError as error:
        raise _suite_error(error) from error
    return CaseResponse.build(case)


@suites_router.delete("/{suite_id}/cases/{case_id}", status_code=204, dependencies=[_MEMBER])
async def delete_case(
    suite_id: UUID,
    case_id: UUID,
    user_context: UserContextDep,
    session: AsyncSession = Depends(get_db_session),
):
    suites = SuiteService(session, user_context)
    existing = await suites.get_case(case_id)
    if existing is None or existing.suite_id != suite_id:
        raise HTTPException(status_code=404, detail="Case not found")
    await suites.delete_case(case_id)
    return Response(status_code=204)


@runs_router.get("", response_model=list[EvalRunResponse], dependencies=[_PER_OBJECT])
async def list_runs(
    agent_id: str,
    user_context: UserContextDep,
    session: AsyncSession = Depends(get_db_session),
    agent_service: AgentService = Depends(get_read_agent_service),
):
    agent = await load_agent(agent_service, agent_id, user_context, "read")
    return [
        EvalRunResponse.build(run)
        for run in await EvalRunService(session, user_context).list_runs(agent.id)
    ]


@runs_router.post("", response_model=EvalRunResponse, status_code=201, dependencies=[_PER_OBJECT])
async def start_run(
    agent_id: str,
    payload: EvalRunCreate,
    user_context: UserContextDep,
    session: AsyncSession = Depends(get_db_session),
    agent_service: AgentService = Depends(get_agent_service),
):
    """Run a suite against the agent's serving revision, or a baseline and a candidate."""
    agent = await load_agent(agent_service, agent_id, user_context, "edit")
    try:
        run = await EvalRunService(session, user_context).create_run(
            payload.suite_id,
            agent,
            baseline_revision_id=payload.baseline_revision_id,
            candidate_revision_id=payload.candidate_revision_id,
            trials=payload.trials,
            concurrency=payload.concurrency,
            budget_usd=payload.budget_usd,
            allow_sandbox=payload.allow_sandbox,
        )
    except EvalRunError as error:
        raise _suite_error(error) from error
    workflow_id = await start_workflow(
        "EvalRunWorkflow",
        f"eval-run-{run.id}",
        {
            "run_id": str(run.id),
            "user_context_data": context_data(user_context),
            "concurrency": run.concurrency,
        },
    )
    run.workflow_id = workflow_id
    await session.commit()
    return EvalRunResponse.build(run)


@runs_router.get("/{run_id}", response_model=EvalRunDetail, dependencies=[_PER_OBJECT])
async def get_run(
    agent_id: str,
    run_id: UUID,
    user_context: UserContextDep,
    session: AsyncSession = Depends(get_db_session),
    agent_service: AgentService = Depends(get_read_agent_service),
):
    agent = await load_agent(agent_service, agent_id, user_context, "read")
    runs = EvalRunService(session, user_context)
    run = await runs.get_run(run_id)
    if run is None or run.agent_id != agent.id:
        raise HTTPException(status_code=404, detail="Run not found")
    cases = await SuiteService(session, user_context).list_cases(run.suite_id)
    return EvalRunDetail(
        **EvalRunResponse.build(run).model_dump(),
        trials_detail=[EvalTrialResponse.build(t) for t in await runs.trials(run.id)],
        cases=[CaseResponse.build(c) for c in cases],
    )


@runs_router.post("/{run_id}/stop", response_model=EvalRunResponse, dependencies=[_PER_OBJECT])
async def stop_run(
    agent_id: str,
    run_id: UUID,
    user_context: UserContextDep,
    session: AsyncSession = Depends(get_db_session),
    agent_service: AgentService = Depends(get_agent_service),
):
    """Stop claiming trials; the ones already running finish and still count."""
    agent = await load_agent(agent_service, agent_id, user_context, "edit")
    runs = EvalRunService(session, user_context)
    run = await runs.get_run(run_id)
    if run is None or run.agent_id != agent.id:
        raise HTTPException(status_code=404, detail="Run not found")
    return EvalRunResponse.build(await runs.stop(run_id, reason="manual"))
