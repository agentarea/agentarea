import uuid
from collections import Counter

from agentarea_evals.runs.workflow import EvalRunWorkflow, ExperimentMonitorWorkflow
from agentarea_evals.runs.workflow_models import (
    CLAIM_TRIALS,
    EVALUATE_EXPERIMENT,
    FINALIZE_RUN,
    POLL_TRIAL,
    START_TRIAL,
    ClaimRequest,
    EvalRunInput,
    ExperimentMonitorInput,
    ExperimentRequest,
    ExperimentState,
    PollRequest,
    STOP_EXPERIMENT,
    PollResult,
    RunRequest,
    StartedTrial,
    StopExperimentRequest,
    TrialRequest,
)
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

CONTEXT = {"user_id": "u", "workspace_id": "w"}


async def test_eval_run_respects_concurrency_and_finalizes_once():
    pending = ["t1", "t2", "t3", "t4"]
    polls: Counter[str] = Counter()
    in_flight: set[str] = set()
    peak = 0
    finalized: list[str] = []

    @activity.defn(name=CLAIM_TRIALS)
    async def claim(request: ClaimRequest) -> list[str]:
        taken = pending[: request.limit]
        del pending[: request.limit]
        return taken

    @activity.defn(name=START_TRIAL)
    async def start(request: TrialRequest) -> StartedTrial:
        nonlocal peak
        if request.trial_id == "t3":
            return StartedTrial(trial_id="t3", error="agent has no model")
        in_flight.add(request.trial_id)
        peak = max(peak, len(in_flight))
        return StartedTrial(trial_id=request.trial_id, task_id=f"task-{request.trial_id}")

    @activity.defn(name=POLL_TRIAL)
    async def poll(request: PollRequest) -> PollResult:
        polls[request.trial_id] += 1
        done = polls[request.trial_id] >= 2
        if done:
            in_flight.discard(request.trial_id)
        return PollResult(done=done)

    @activity.defn(name=FINALIZE_RUN)
    async def finalize(request: RunRequest) -> None:
        finalized.append(request.run_id)

    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        queue = str(uuid.uuid4())
        async with Worker(
            env.client,
            task_queue=queue,
            workflows=[EvalRunWorkflow],
            activities=[claim, start, poll, finalize],
        ):
            await env.client.execute_workflow(
                EvalRunWorkflow.run,
                EvalRunInput(run_id="run-1", user_context_data=CONTEXT, concurrency=2),
                id=str(uuid.uuid4()),
                task_queue=queue,
            )

    assert finalized == ["run-1"]
    assert peak <= 2
    assert set(polls) == {"t1", "t2", "t4"}
    assert all(count == 2 for count in polls.values())


async def test_experiment_monitor_stops_when_the_experiment_ends():
    evaluations: list[str] = []

    @activity.defn(name=EVALUATE_EXPERIMENT)
    async def evaluate(request: ExperimentRequest) -> ExperimentState:
        evaluations.append(request.experiment_id)
        return ExperimentState(running=len(evaluations) < 3)

    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        queue = str(uuid.uuid4())
        async with Worker(
            env.client, task_queue=queue, workflows=[ExperimentMonitorWorkflow],
            activities=[evaluate],
        ):
            await env.client.execute_workflow(
                ExperimentMonitorWorkflow.run,
                ExperimentMonitorInput(
                    agent_id="a", experiment_id="e", user_context_data=CONTEXT
                ),
                id=str(uuid.uuid4()),
                task_queue=queue,
            )

    assert evaluations == ["e", "e", "e"]


async def test_a_monitor_that_cannot_evaluate_stops_the_experiment():
    stopped: list[tuple[str, str]] = []

    @activity.defn(name=EVALUATE_EXPERIMENT)
    async def evaluate(request: ExperimentRequest) -> ExperimentState:
        raise ApplicationError("stats query broke", non_retryable=True)

    @activity.defn(name=STOP_EXPERIMENT)
    async def stop(request: StopExperimentRequest) -> None:
        stopped.append((request.experiment_id, request.reason))

    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        queue = str(uuid.uuid4())
        async with Worker(
            env.client, task_queue=queue, workflows=[ExperimentMonitorWorkflow],
            activities=[evaluate, stop],
        ):
            await env.client.execute_workflow(
                ExperimentMonitorWorkflow.run,
                ExperimentMonitorInput(
                    agent_id="a", experiment_id="e", user_context_data=CONTEXT
                ),
                id=str(uuid.uuid4()),
                task_queue=queue,
            )

    assert len(stopped) == 1
    assert stopped[0][0] == "e"
    assert stopped[0][1] == "monitor_failed"


async def test_a_brief_outage_does_not_stop_the_experiment():
    attempts: list[int] = []
    stopped: list[str] = []

    @activity.defn(name=EVALUATE_EXPERIMENT)
    async def evaluate(request: ExperimentRequest) -> ExperimentState:
        attempts.append(activity.info().attempt)
        if len(attempts) < 8:
            raise RuntimeError("database restarting")
        return ExperimentState(running=False)

    @activity.defn(name=STOP_EXPERIMENT)
    async def stop(request: StopExperimentRequest) -> None:
        stopped.append(request.reason)

    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        queue = str(uuid.uuid4())
        async with Worker(
            env.client, task_queue=queue, workflows=[ExperimentMonitorWorkflow],
            activities=[evaluate, stop],
        ):
            await env.client.execute_workflow(
                ExperimentMonitorWorkflow.run,
                ExperimentMonitorInput(
                    agent_id="a", experiment_id="e", user_context_data=CONTEXT
                ),
                id=str(uuid.uuid4()),
                task_queue=queue,
            )

    assert len(attempts) == 8
    assert stopped == []
