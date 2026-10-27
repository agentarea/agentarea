"""Brings every cron trigger's schedule to what its trigger says, run by a Temporal Schedule."""

from datetime import timedelta
from typing import TYPE_CHECKING

from temporalio import workflow
from temporalio.common import RetryPolicy

SYNC_CRON_SCHEDULES = "sync_cron_schedules_activity"
SCHEDULE_ID = "cron-schedule-sync"
SYNC_EVERY = timedelta(minutes=5)

if TYPE_CHECKING:
    from temporalio.client import Client, ScheduleUpdateInput


@workflow.defn
class CronScheduleSyncWorkflow:
    @workflow.run
    async def run(self) -> None:
        # One attempt: the next tick is the retry.
        await workflow.execute_activity(
            SYNC_CRON_SCHEDULES,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


async def ensure_cron_schedule_sync_schedule(client: Client, task_queue: str) -> None:
    """Create the sync's schedule, or bring an existing one up to date."""
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
            CronScheduleSyncWorkflow.run, id=SCHEDULE_ID, task_queue=task_queue
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=SYNC_EVERY)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    def replace(_: ScheduleUpdateInput) -> ScheduleUpdate:
        return ScheduleUpdate(schedule=schedule)

    try:
        await client.create_schedule(SCHEDULE_ID, schedule)
    except ScheduleAlreadyRunningError:
        await client.get_schedule_handle(SCHEDULE_ID).update(replace)
