"""Starts tasks left pending with no workflow, run by a Temporal Schedule."""

from datetime import timedelta
from typing import TYPE_CHECKING

from temporalio import workflow
from temporalio.common import RetryPolicy

START_UNDISPATCHED_TASKS = "start_undispatched_tasks_activity"
SCHEDULE_ID = "undispatched-task-reconciler"
RECONCILE_EVERY = timedelta(minutes=1)

if TYPE_CHECKING:
    from temporalio.client import Client, ScheduleUpdateInput


@workflow.defn
class UndispatchedTaskReconcilerWorkflow:
    @workflow.run
    async def run(self) -> int:
        # One attempt: the next tick is the retry.
        return await workflow.execute_activity(
            START_UNDISPATCHED_TASKS,
            result_type=int,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


async def ensure_undispatched_task_schedule(client: "Client", task_queue: str) -> None:
    """Create the reconciler's schedule, or bring an existing one up to date."""
    from temporalio.client import (
        Schedule,
        ScheduleActionStartWorkflow,
        ScheduleAlreadyRunningError,
        ScheduleIntervalSpec,
        ScheduleOverlapPolicy,
        SchedulePolicy,
        ScheduleSpec,
        ScheduleUpdate,
    )

    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            UndispatchedTaskReconcilerWorkflow.run, id=SCHEDULE_ID, task_queue=task_queue
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=RECONCILE_EVERY)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    def replace(_: "ScheduleUpdateInput") -> ScheduleUpdate:
        return ScheduleUpdate(schedule=schedule)

    try:
        await client.create_schedule(SCHEDULE_ID, schedule)
    except ScheduleAlreadyRunningError:
        await client.get_schedule_handle(SCHEDULE_ID).update(replace)
