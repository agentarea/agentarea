"""Durable drivers: run a suite's trials, and keep an experiment evaluated.

Both run on the existing worker; the activities do the work.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
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
        PollResult,
        RunRequest,
        StartedTrial,
        TrialRequest,
    )

_ACTIVITY_TIMEOUT = timedelta(minutes=2)
_RETRY = RetryPolicy(maximum_attempts=5)


@workflow.defn
class EvalRunWorkflow:
    @workflow.run
    async def run(self, request: EvalRunInput) -> None:
        running: dict[str, tuple[str, float]] = {}
        context = request.user_context_data
        while True:
            claimed: list[str] = []
            free = request.concurrency - len(running)
            if free > 0:
                claimed = await workflow.execute_activity(
                    CLAIM_TRIALS,
                    ClaimRequest(run_id=request.run_id, user_context_data=context, limit=free),
                    result_type=list[str],
                    start_to_close_timeout=_ACTIVITY_TIMEOUT,
                    retry_policy=_RETRY,
                )
                for trial_id in claimed:
                    started = await workflow.execute_activity(
                        START_TRIAL,
                        TrialRequest(trial_id=trial_id, user_context_data=context),
                        result_type=StartedTrial,
                        start_to_close_timeout=_ACTIVITY_TIMEOUT,
                        retry_policy=_RETRY,
                    )
                    if started.task_id:
                        running[trial_id] = (started.task_id, workflow.time())
            if not running and not claimed:
                break

            await workflow.sleep(timedelta(seconds=request.poll_seconds))
            for trial_id, (task_id, started_at) in list(running.items()):
                polled = await workflow.execute_activity(
                    POLL_TRIAL,
                    PollRequest(
                        trial_id=trial_id,
                        task_id=task_id,
                        user_context_data=context,
                        elapsed_seconds=int(workflow.time() - started_at),
                        timeout_seconds=request.trial_timeout_seconds,
                    ),
                    result_type=PollResult,
                    start_to_close_timeout=_ACTIVITY_TIMEOUT,
                    retry_policy=_RETRY,
                )
                if polled.done:
                    del running[trial_id]

        await workflow.execute_activity(
            FINALIZE_RUN,
            RunRequest(run_id=request.run_id, user_context_data=context),
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_RETRY,
        )


@workflow.defn
class ExperimentMonitorWorkflow:
    @workflow.run
    async def run(self, request: ExperimentMonitorInput) -> None:
        for _ in range(request.evaluations_before_continue_as_new):
            await workflow.sleep(timedelta(seconds=request.interval_seconds))
            state = await workflow.execute_activity(
                EVALUATE_EXPERIMENT,
                ExperimentRequest(
                    agent_id=request.agent_id,
                    experiment_id=request.experiment_id,
                    user_context_data=request.user_context_data,
                ),
                result_type=ExperimentState,
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=_RETRY,
            )
            if not state.running:
                return
        workflow.continue_as_new(request)
