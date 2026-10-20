"""Integration tests for TemporalScheduleManager against a REAL Temporal server.

These exercise the Temporal Schedules API end-to-end on a SQLite-backed dev
server (``WorkflowEnvironment.start_local`` -- see the ``temporal_sqlite_client``
fixture). The in-memory time-skipping test server does NOT implement the
Schedules API, so this coverage is only possible with the real server.

The mocked unit tests in ``test_temporal_schedule_manager.py`` verify call shape
(that the manager calls ``create_schedule`` with the right arguments); these
verify that Temporal actually stores the schedule and round-trips it through
``describe`` -- catching encoding, spec-mapping and lifecycle bugs that mocks
cannot. See ``test_get_schedule_info_loses_cron_expression`` for one such bug
this suite surfaced.
"""

import uuid

import pytest
from agentarea_triggers.logging_utils import TriggerExecutionError
from agentarea_triggers.temporal_schedule_manager import TemporalScheduleManager

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_schedule_lifecycle_round_trips(temporal_sqlite_client):
    """Apply creates, changes, pauses and resumes a schedule; delete removes it.

    Every assertion goes through the schedule handle (``describe``), which is
    strongly consistent, so the test is deterministic without polling.
    """
    manager = TemporalScheduleManager(temporal_sqlite_client)
    trigger_id = uuid.uuid4()

    assert await manager.apply_cron_schedule(trigger_id, "0 9 * * *", "UTC", paused=False)
    info = await manager.get_schedule_info(trigger_id)
    assert info is not None
    assert info["schedule_id"] == f"cron-trigger-{trigger_id}"
    assert info["trigger_id"] == str(trigger_id)
    assert (info["cron_expressions"], info["timezone"], info["paused"]) == (
        ["0 9 * * *"],
        "UTC",
        False,
    )

    assert await manager.apply_cron_schedule(
        trigger_id, "30 18 * * 1-5", "Europe/Berlin", paused=False
    )
    info = await manager.get_schedule_info(trigger_id)
    assert (info["cron_expressions"], info["timezone"]) == (["30 18 * * 1-5"], "Europe/Berlin")

    assert await manager.apply_cron_schedule(
        trigger_id, "30 18 * * 1-5", "Europe/Berlin", paused=True
    )
    assert (await manager.get_schedule_info(trigger_id))["paused"] is True
    assert await manager.apply_cron_schedule(
        trigger_id, "30 18 * * 1-5", "Europe/Berlin", paused=False
    )
    assert (await manager.get_schedule_info(trigger_id))["paused"] is False

    await manager.delete_cron_schedule(trigger_id)
    assert await manager.get_schedule_info(trigger_id) is None


async def test_applying_what_the_schedule_already_is_changes_nothing(temporal_sqlite_client):
    manager = TemporalScheduleManager(temporal_sqlite_client)
    trigger_id = uuid.uuid4()
    await manager.apply_cron_schedule(trigger_id, "0 9 * * *", "Asia/Tokyo", paused=True)
    try:
        assert not await manager.apply_cron_schedule(
            trigger_id, "0 9 * * *", "Asia/Tokyo", paused=True
        )
    finally:
        await manager.delete_cron_schedule(trigger_id)


async def test_get_schedule_info_reports_cron_expression(temporal_sqlite_client):
    """Regression: get_schedule_info reports the cron expression on a real server.

    Temporal normalises ``cron_expressions`` into a structured calendar spec, so
    ``spec.cron_expressions`` is empty on ``describe()``. ``get_schedule_info``
    recovers the original expression from the schedule action args. This test
    fails against the unpatched manager (it returned ``[]``); the mocked unit
    test could not catch the gap.
    """
    manager = TemporalScheduleManager(temporal_sqlite_client)
    trigger_id = uuid.uuid4()
    try:
        await manager.create_cron_schedule(trigger_id, "0 9 * * *", "UTC")
        info = await manager.get_schedule_info(trigger_id)
        assert info["cron_expressions"] == ["0 9 * * *"]
    finally:
        await manager.delete_cron_schedule(trigger_id)


async def test_get_active_schedule_count_counts_cron_schedules(temporal_sqlite_client):
    """Regression: get_active_schedule_count lists schedules on a real server.

    ``Client.list_schedules()`` is a coroutine returning an async iterator, so it
    must be awaited before iterating. The unpatched manager did ``async for ... in
    list_schedules()`` (no await) and raised against a real server -- the mocked
    tests never exercised the iteration. This is consumed by health_checks.py.
    """
    manager = TemporalScheduleManager(temporal_sqlite_client)
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    try:
        await manager.create_cron_schedule(t1, "0 9 * * *", "UTC")
        await manager.create_cron_schedule(t2, "0 10 * * *", "UTC")
        assert await manager.get_active_schedule_count() >= 2
    finally:
        await manager.delete_cron_schedule(t1)
        await manager.delete_cron_schedule(t2)


async def test_create_existing_schedule_raises(temporal_sqlite_client):
    """Creating the same schedule twice surfaces a TriggerExecutionError.

    The mocked test simulates this with a side_effect; here the real server
    rejects the duplicate, proving the manager maps the Temporal error correctly.
    """
    manager = TemporalScheduleManager(temporal_sqlite_client)
    trigger_id = uuid.uuid4()

    await manager.create_cron_schedule(trigger_id, "0 9 * * *", "UTC")
    try:
        with pytest.raises(TriggerExecutionError):
            await manager.create_cron_schedule(trigger_id, "0 9 * * *", "UTC")
    finally:
        await manager.delete_cron_schedule(trigger_id)


async def test_delete_missing_schedule_is_noop(temporal_sqlite_client):
    """Deleting a non-existent schedule is a no-op (no raise) on a real server."""
    manager = TemporalScheduleManager(temporal_sqlite_client)
    await manager.delete_cron_schedule(uuid.uuid4())


async def test_a_backfilled_slot_reaches_the_trigger_as_its_scheduled_time(temporal_sqlite_client):
    """The firing carries the slot it was scheduled for, not when the schedule was saved."""
    import asyncio
    from datetime import UTC, datetime, timedelta

    from agentarea_common.workflow.sandbox import create_workflow_runner
    from agentarea_execution.models import (
        EvaluateTriggerConditionsRequest,
        EvaluateTriggerConditionsResult,
    )
    from agentarea_execution.workflows.trigger_execution_workflow import TriggerExecutionWorkflow
    from agentarea_triggers.temporal_schedule_manager import DEFAULT_TASK_QUEUE
    from temporalio import activity
    from temporalio.client import ScheduleBackfill, ScheduleOverlapPolicy
    from temporalio.worker import Worker

    seen: asyncio.Queue[dict] = asyncio.Queue()

    @activity.defn(name="evaluate_trigger_conditions_activity")
    async def evaluate(
        request: EvaluateTriggerConditionsRequest,
    ) -> EvaluateTriggerConditionsResult:
        await seen.put(request.event_data)
        return EvaluateTriggerConditionsResult(conditions_met=False, trigger_id=request.trigger_id)

    manager = TemporalScheduleManager(temporal_sqlite_client)
    trigger_id = uuid.uuid4()
    slot = datetime(2026, 1, 5, 9, tzinfo=UTC)
    await manager.create_cron_schedule(trigger_id, "0 9 * * *", "UTC", paused=True)
    try:
        async with Worker(
            temporal_sqlite_client,
            task_queue=DEFAULT_TASK_QUEUE,
            workflows=[TriggerExecutionWorkflow],
            activities=[evaluate],
            workflow_runner=create_workflow_runner(),
        ):
            await temporal_sqlite_client.get_schedule_handle(
                f"cron-trigger-{trigger_id}"
            ).backfill(
                ScheduleBackfill(
                    start_at=slot - timedelta(minutes=1),
                    end_at=slot + timedelta(minutes=1),
                    overlap=ScheduleOverlapPolicy.ALLOW_ALL,
                )
            )
            event_data = await asyncio.wait_for(seen.get(), timeout=30)
    finally:
        await manager.delete_cron_schedule(trigger_id)

    assert event_data["scheduled_time"] == slot.isoformat()
    assert "execution_time" not in event_data


async def test_a_schedule_catches_up_missed_slots_only_within_the_window(temporal_sqlite_client):
    from agentarea_triggers.temporal_schedule_manager import CATCHUP_WINDOW

    manager = TemporalScheduleManager(temporal_sqlite_client)
    trigger_id = uuid.uuid4()
    handle = temporal_sqlite_client.get_schedule_handle(f"cron-trigger-{trigger_id}")
    await manager.apply_cron_schedule(trigger_id, "0 9 * * *", "UTC", paused=False)
    try:
        created = (await handle.describe()).schedule.policy.catchup_window
        await manager.apply_cron_schedule(trigger_id, "0 10 * * *", "UTC", paused=False)
        changed = (await handle.describe()).schedule.policy.catchup_window
    finally:
        await manager.delete_cron_schedule(trigger_id)

    assert (created, changed) == (CATCHUP_WINDOW, CATCHUP_WINDOW)


async def test_apply_brings_a_schedule_of_the_old_shape_up_to_date(temporal_sqlite_client):
    """A schedule saved before the slot time and catch-up window gains both."""
    from agentarea_triggers.temporal_schedule_manager import CATCHUP_WINDOW, DEFAULT_TASK_QUEUE
    from temporalio.client import (
        Schedule,
        ScheduleActionStartWorkflow,
        ScheduleSpec,
        ScheduleState,
    )

    manager = TemporalScheduleManager(temporal_sqlite_client)
    trigger_id = uuid.uuid4()
    schedule_id = f"cron-trigger-{trigger_id}"
    await temporal_sqlite_client.create_schedule(
        schedule_id,
        Schedule(
            action=ScheduleActionStartWorkflow(
                "TriggerExecutionWorkflow",
                args=[
                    trigger_id,
                    {
                        "execution_time": "2025-01-01T00:00:00",
                        "source": "cron",
                        "cron_expression": "0 9 * * *",
                        "timezone": "Europe/Berlin",
                    },
                ],
                id=f"trigger-execution-{trigger_id}-{{{{.ScheduledTime}}}}",
                task_queue=DEFAULT_TASK_QUEUE,
            ),
            spec=ScheduleSpec(cron_expressions=["0 9 * * *"], time_zone_name="Europe/Berlin"),
            state=ScheduleState(paused=True),
        ),
    )
    try:
        brought_up_to_date = await manager.apply_cron_schedule(
            trigger_id, "0 9 * * *", "Europe/Berlin", paused=True
        )
        again = await manager.apply_cron_schedule(
            trigger_id, "0 9 * * *", "Europe/Berlin", paused=True
        )
        description = await temporal_sqlite_client.get_schedule_handle(schedule_id).describe()
        info = await manager.get_schedule_info(trigger_id)
    finally:
        await manager.delete_cron_schedule(trigger_id)

    payload = temporal_sqlite_client.data_converter.payload_converter.from_payloads(
        [description.schedule.action.args[1]]
    )[0]
    assert (brought_up_to_date, again) == (True, False)
    assert description.schedule.policy.catchup_window == CATCHUP_WINDOW
    assert payload == {"source": "cron", "cron_expression": "0 9 * * *", "timezone": "Europe/Berlin"}
    assert (info["cron_expressions"], info["timezone"], info["paused"]) == (
        ["0 9 * * *"],
        "Europe/Berlin",
        True,
    )


async def test_schedules_of_triggers_that_are_gone_are_deleted(temporal_sqlite_client):
    """Only trigger schedules are swept; a schedule of anything else is not ours to delete."""
    from datetime import timedelta

    from temporalio.client import (
        Schedule,
        ScheduleActionStartWorkflow,
        ScheduleIntervalSpec,
        ScheduleSpec,
    )

    manager = TemporalScheduleManager(temporal_sqlite_client)
    kept, gone = uuid.uuid4(), uuid.uuid4()
    for trigger_id in (kept, gone):
        await manager.apply_cron_schedule(trigger_id, "0 9 * * *", "UTC", paused=False)
    await temporal_sqlite_client.create_schedule(
        "someone-elses-schedule",
        Schedule(
            action=ScheduleActionStartWorkflow("Other", id="other", task_queue="other"),
            spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=1))]),
        ),
    )
    try:
        removed = await manager.delete_cron_schedules_except({kept})
        remaining = {
            listed.id async for listed in await temporal_sqlite_client.list_schedules()
        }
    finally:
        await manager.delete_cron_schedule(kept)

    assert removed == 1
    assert f"cron-trigger-{gone}" not in remaining
    assert {f"cron-trigger-{kept}", "someone-elses-schedule"} <= remaining
