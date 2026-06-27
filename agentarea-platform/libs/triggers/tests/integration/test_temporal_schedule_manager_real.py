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
    """Create -> describe -> update -> pause/unpause -> delete on a real server.

    Every assertion goes through the schedule handle (``describe``), which is
    strongly consistent, so the test is deterministic without polling. It asserts
    only on fields the real server round-trips faithfully; cron-expression
    reporting is covered (as a known bug) by the xfail test below.
    """
    manager = TemporalScheduleManager(temporal_sqlite_client)
    trigger_id = uuid.uuid4()

    # create
    schedule_id = await manager.create_cron_schedule(trigger_id, "0 9 * * *", "UTC")
    assert schedule_id == f"cron-trigger-{trigger_id}"

    # describe round-trips the metadata we set, including the cron expression
    info = await manager.get_schedule_info(trigger_id)
    assert info is not None
    assert info["schedule_id"] == schedule_id
    assert info["trigger_id"] == str(trigger_id)
    assert info["cron_expressions"] == ["0 9 * * *"]
    assert info["timezone"] == "UTC"
    assert info["paused"] is False

    # update changes the cron expression and timezone
    await manager.update_cron_schedule(trigger_id, "30 18 * * 1-5", "Europe/Berlin")
    info = await manager.get_schedule_info(trigger_id)
    assert info["cron_expressions"] == ["30 18 * * 1-5"]
    assert info["timezone"] == "Europe/Berlin"

    # pause / unpause are reflected in describe
    await manager.pause_cron_schedule(trigger_id)
    assert (await manager.get_schedule_info(trigger_id))["paused"] is True
    await manager.unpause_cron_schedule(trigger_id)
    assert (await manager.get_schedule_info(trigger_id))["paused"] is False

    # delete removes it; describe then reports None
    await manager.delete_cron_schedule(trigger_id)
    assert await manager.get_schedule_info(trigger_id) is None


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
