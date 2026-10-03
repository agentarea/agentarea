"""Activities behind the eval workflows. They run on the existing worker."""

from typing import Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.base.tenant_scope import bind_workspace_scope
from agentarea_common.config import get_database
from temporalio import activity

from agentarea_evals.experiments.service import ExperimentService
from agentarea_evals.outcomes.classify import Outcome, classify
from agentarea_evals.runs.outcome import task_status, trial_outcome
from agentarea_evals.runs.service import EvalRunService
from agentarea_evals.runs.workflow_models import (
    CLAIM_TRIALS,
    EVALUATE_EXPERIMENT,
    FINALIZE_RUN,
    POLL_TRIAL,
    START_TRIAL,
    ClaimRequest,
    ExperimentRequest,
    ExperimentState,
    PollRequest,
    PollResult,
    RunRequest,
    StartedTrial,
    TrialRequest,
)

# Nobody answers an evaluation run; waiting on a person means the trial is over.
_WAITING_ON_A_PERSON = {"waiting_for_input", "waiting_for_approval"}


def _context(data: dict[str, Any]) -> UserContext:
    context = UserContext(user_id=data["user_id"], workspace_id=data["workspace_id"])
    bind_workspace_scope(context.workspace_id)
    return context


def make_eval_activities(dependencies: Any) -> list[Any]:
    """``dependencies`` must carry ``event_broker`` and ``workflow_executor``."""

    def _session():
        database = get_database()
        if database is None:
            raise RuntimeError("the eval activities need a database")
        return database.async_session_factory()

    def _task_service(session, context: UserContext):
        from agentarea_tasks.infrastructure.repository import TaskRepository
        from agentarea_tasks.task_service import TaskService
        from agentarea_tasks.temporal_task_manager import TemporalTaskManager

        factory = RepositoryFactory(session, context)
        return TaskService(
            repository_factory=factory,
            event_broker=dependencies.event_broker,
            task_manager=TemporalTaskManager(
                task_repository=factory.create_repository(TaskRepository),
                temporal_executor=dependencies.workflow_executor,
            ),
        )

    def _agent_service(session, context: UserContext):
        from agentarea_agents.application.agent_service import AgentService
        from agentarea_common.auth.authorization import AuthorizationService
        from agentarea_common.di.container import resolve

        return AgentService(
            RepositoryFactory(session, context),
            dependencies.event_broker,
            authorization_service=resolve(AuthorizationService),
        )

    @activity.defn(name=CLAIM_TRIALS)
    async def claim_trials(request: ClaimRequest) -> list[str]:
        context = _context(request.user_context_data)
        async with _session() as session:
            trials = await EvalRunService(session, context).claim(
                UUID(request.run_id), limit=request.limit
            )
            return [str(trial.id) for trial in trials]

    @activity.defn(name=START_TRIAL)
    async def start_trial(request: TrialRequest) -> StartedTrial:
        context = _context(request.user_context_data)
        async with _session() as session:
            runs = EvalRunService(session, context)
            spec = await runs.trial_spec(UUID(request.trial_id))
            try:
                task = await _task_service(session, context).create_and_execute_task_with_workflow(
                    agent_id=UUID(spec["agent_id"]),
                    description=spec["input"],
                    workspace_id=context.workspace_id,
                    parameters=spec["parameters"],
                    user_id=context.user_id,
                    metadata_overrides=spec["metadata"],
                    agent_revision_id=UUID(spec["revision_id"]),
                )
            except ValueError as error:
                await runs.record_error(UUID(request.trial_id), f"could not start: {error}")
                return StartedTrial(trial_id=request.trial_id, error=str(error))
            await runs.attach_task(UUID(request.trial_id), task.id)
            return StartedTrial(trial_id=request.trial_id, task_id=str(task.id))

    @activity.defn(name=POLL_TRIAL)
    async def poll_trial(request: PollRequest) -> PollResult:
        context = _context(request.user_context_data)
        trial_id, task_id = UUID(request.trial_id), UUID(request.task_id)
        async with _session() as session:
            runs = EvalRunService(session, context)
            status = await task_status(session, context, task_id)
            if classify(status, ratings=[]) is not Outcome.PENDING:
                await runs.record_outcome(trial_id, await trial_outcome(session, context, task_id))
                return PollResult(done=True)
            reason = None
            if status in _WAITING_ON_A_PERSON:
                reason = f"the run stopped to wait for a person ({status})"
            elif request.elapsed_seconds >= request.timeout_seconds:
                reason = f"the run did not finish within {request.timeout_seconds}s"
            if reason is None:
                return PollResult(done=False)
            await _task_service(session, context).cancel_task(task_id)
            outcome = await trial_outcome(session, context, task_id)
            await runs.record_error(trial_id, reason, cost_usd=outcome.cost_usd)
            return PollResult(done=True)

    @activity.defn(name=FINALIZE_RUN)
    async def finalize_run(request: RunRequest) -> None:
        context = _context(request.user_context_data)
        async with _session() as session:
            await EvalRunService(session, context).finalize(UUID(request.run_id))

    @activity.defn(name=EVALUATE_EXPERIMENT)
    async def evaluate_experiment(request: ExperimentRequest) -> ExperimentState:
        context = _context(request.user_context_data)
        async with _session() as session:
            agents = _agent_service(session, context)
            experiments = ExperimentService(
                session,
                context,
                activate=agents.activate_revision,
                offline_passed=EvalRunService(session, context).offline_passed,
            )
            experiment = await experiments.get(UUID(request.agent_id), UUID(request.experiment_id))
            if experiment is None:
                return ExperimentState(running=False)
            await experiments.evaluate(experiment)
            return ExperimentState(running=experiment.status == "running")

    return [claim_trials, start_trial, poll_trial, finalize_run, evaluate_experiment]
