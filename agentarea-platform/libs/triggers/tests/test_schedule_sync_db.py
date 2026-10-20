"""Every cron trigger's schedule is brought to what the triggers table says, across workspaces.

What Temporal does with each schedule is covered against a real server in
``integration/test_temporal_schedule_manager_real.py``; here the schedules are
recorded. Set STREAMS_TEST_DATABASE_URL.
"""

import os
from uuid import UUID, uuid4

import pytest
from agentarea_triggers.schedule_sync import sync_cron_schedules
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")


class _Schedules:
    def __init__(self, failing: set[UUID] | None = None):
        self.failing = failing or set()
        self.applied: dict[UUID, tuple[str, str, bool]] = {}
        self.kept: set[UUID] | None = None

    async def apply_cron_schedule(
        self, trigger_id: UUID, cron_expression: str, timezone: str, *, paused: bool
    ) -> bool:
        if trigger_id in self.failing:
            raise ConnectionError("Temporal is unavailable")
        self.applied[trigger_id] = (cron_expression, timezone, paused)
        return True

    async def delete_cron_schedules_except(self, keep: set[UUID]) -> int:
        self.kept = set(keep)
        return 0


@pytest.fixture
async def maker():
    engine = create_async_engine(TEST_DATABASE_URL)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _trigger(maker, *, trigger_type="cron", active=True, timezone="UTC") -> UUID:
    trigger_id = uuid4()
    async with maker() as session:
        await session.execute(
            text(
                "INSERT INTO triggers (id, workspace_id, created_by, name, description, "
                "agent_id, trigger_type, is_active, task_parameters, conditions, "
                "failure_threshold, consecutive_failures, cron_expression, timezone, "
                "created_at, updated_at) VALUES (:id, :ws, 'owner', 't', '', :a, :type, "
                ":active, '{}', '{}', 5, 0, :cron, :tz, now(), now())"
            ),
            {
                "id": trigger_id,
                "ws": str(uuid4()),
                "a": uuid4(),
                "type": trigger_type,
                "active": active,
                "cron": "0 9 * * *" if trigger_type == "cron" else None,
                "tz": timezone,
            },
        )
        await session.commit()
    return trigger_id


async def test_each_cron_trigger_gets_the_schedule_its_row_describes(maker):
    active = await _trigger(maker)
    stopped = await _trigger(maker, active=False, timezone="Europe/Berlin")
    stream = await _trigger(maker, trigger_type="stream")
    schedules = _Schedules()

    report = await sync_cron_schedules(maker, schedules)

    assert schedules.applied[active] == ("0 9 * * *", "UTC", False)
    assert schedules.applied[stopped] == ("0 9 * * *", "Europe/Berlin", True)
    assert stream not in schedules.applied
    assert schedules.kept is not None
    assert {active, stopped} <= schedules.kept
    assert stream not in schedules.kept
    assert report.failed == 0


async def test_a_schedule_temporal_refuses_does_not_hold_back_the_rest(maker):
    refused, fine = await _trigger(maker), await _trigger(maker)
    schedules = _Schedules(failing={refused})

    report = await sync_cron_schedules(maker, schedules)

    assert fine in schedules.applied
    assert report.failed >= 1
    assert schedules.kept is not None
    assert refused in schedules.kept
