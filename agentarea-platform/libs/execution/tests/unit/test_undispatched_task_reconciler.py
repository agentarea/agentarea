"""The reconciler workflow runs its activity once per tick, on a schedule that never overlaps."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentarea_common.workflow.sandbox import create_workflow_runner
from agentarea_execution.workflows.undispatched_task_reconciler_workflow import (
    RECONCILE_EVERY,
    SCHEDULE_ID,
    START_UNDISPATCHED_TASKS,
    UndispatchedTaskReconcilerWorkflow,
    ensure_undispatched_task_schedule,
)
from temporalio import activity
from temporalio.client import ScheduleAlreadyRunningError, ScheduleOverlapPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker


async def test_a_tick_runs_the_activity_once_and_returns_how_many_started():
    calls = []

    @activity.defn(name=START_UNDISPATCHED_TASKS)
    async def start_undispatched_tasks() -> int:
        calls.append(1)
        return 3

    async with await WorkflowEnvironment.start_time_skipping() as env:
        task_queue = str(uuid.uuid4())
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[UndispatchedTaskReconcilerWorkflow],
            activities=[start_undispatched_tasks],
            workflow_runner=create_workflow_runner(),
        ):
            started = await env.client.execute_workflow(
                UndispatchedTaskReconcilerWorkflow.run, id=str(uuid.uuid4()), task_queue=task_queue
            )
    assert started == 3
    assert calls == [1]


async def test_the_schedule_is_created_every_minute_without_overlap():
    client = MagicMock()
    client.create_schedule = AsyncMock()
    await ensure_undispatched_task_schedule(client, "agent-tasks")
    schedule_id, schedule = client.create_schedule.await_args.args
    assert schedule_id == SCHEDULE_ID
    assert schedule.action.task_queue == "agent-tasks"
    assert schedule.spec.intervals[0].every == RECONCILE_EVERY
    assert schedule.policy.overlap is ScheduleOverlapPolicy.SKIP


async def test_an_existing_schedule_is_updated_in_place():
    client = MagicMock()
    client.create_schedule = AsyncMock(side_effect=ScheduleAlreadyRunningError())
    handle = MagicMock()
    handle.update = AsyncMock()
    client.get_schedule_handle.return_value = handle
    await ensure_undispatched_task_schedule(client, "agent-tasks")
    client.get_schedule_handle.assert_called_once_with(SCHEDULE_ID)
    updater = handle.update.await_args.args[0]
    assert updater(None).schedule.action.task_queue == "agent-tasks"


@pytest.mark.parametrize("name", [START_UNDISPATCHED_TASKS])
def test_the_worker_registers_the_activity_by_the_name_the_workflow_schedules(name):
    from agentarea_execution.activities.undispatched_task_activities import (
        make_undispatched_task_activities,
    )

    (fn,) = make_undispatched_task_activities(MagicMock())
    assert activity._Definition.must_from_callable(fn).name == name
