"""A fired task's end counts towards its trigger's failure_threshold, against the migrated schema.

Starting a task is not a success: a trigger whose every task fails used to read
0 consecutive failures. Set STREAMS_TEST_DATABASE_URL.
"""

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.events.task_stream import task_event
from agentarea_triggers.domain.enums import ExecutionStatus
from agentarea_triggers.logging_utils import FiringNotRecordedError
from agentarea_triggers.run_outcomes import TriggerRunOutcomes
from agentarea_triggers.trigger_service import TriggerService
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")

THRESHOLD = 3


class _Setup:
    def __init__(self, maker, workspace_id: str, trigger_id: UUID):
        self.maker = maker
        self.workspace_id = workspace_id
        self.trigger_id = trigger_id
        self.schedules = AsyncMock()
        self.outcomes = TriggerRunOutcomes(session_factory=maker, trigger_service=self._service)

    def _service(self, session: AsyncSession, context: UserContext) -> TriggerService:
        return TriggerService(
            repository_factory=RepositoryFactory(session, context),
            event_broker=AsyncMock(),
            temporal_schedule_manager=self.schedules,
        )

    async def fired_task(self, *, origin_type: str | None = "trigger", fired: bool = True) -> UUID:
        task_id = uuid4()
        async with self.maker() as session:
            await session.execute(
                text(
                    "INSERT INTO tasks (id, agent_id, description, status, workspace_id, "
                    "created_by, origin_type, origin_id) VALUES (:id, :agent, 'd', 'running', "
                    ":ws, 'owner', :origin_type, :origin_id)"
                ),
                {
                    "id": task_id,
                    "agent": uuid4(),
                    "ws": self.workspace_id,
                    "origin_type": origin_type,
                    "origin_id": str(self.trigger_id) if origin_type == "trigger" else None,
                },
            )
            if fired:
                await session.execute(
                    text(
                        "INSERT INTO trigger_executions (id, workspace_id, created_by, trigger_id, "
                        "executed_at, status, task_id, execution_time_ms, trigger_data, "
                        "derived_event_ids, created_at, updated_at) VALUES (:id, :ws, 'owner', "
                        ":trigger, now(), 'success', :task, 5, '{}', '[]', now(), now())"
                    ),
                    {
                        "id": uuid4(),
                        "ws": self.workspace_id,
                        "trigger": self.trigger_id,
                        "task": task_id,
                    },
                )
            await session.commit()
        return task_id

    async def ended(self, task_id: UUID, event_type: str, **data) -> None:
        await self.outcomes.handle(
            task_event(
                task_id=str(task_id),
                workspace_id=self.workspace_id,
                event_type=event_type,
                event_id=str(uuid4()),
                timestamp=datetime.now(UTC),
                data=data,
            )
        )

    async def trigger(self):
        async with self.maker() as session:
            return (
                await session.execute(
                    text("SELECT consecutive_failures, is_active FROM triggers WHERE id = :id"),
                    {"id": self.trigger_id},
                )
            ).one()

    async def firing_of(self, task_id: UUID):
        async with self.maker() as session:
            return (
                await session.execute(
                    text("SELECT status, error_message FROM trigger_executions WHERE task_id = :t"),
                    {"t": task_id},
                )
            ).one()


@pytest.fixture
async def setup():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    workspace_id, trigger_id = str(uuid4()), uuid4()
    async with maker() as session:
        await session.execute(
            text(
                "INSERT INTO triggers (id, workspace_id, created_by, name, description, agent_id, "
                "trigger_type, is_active, task_parameters, conditions, failure_threshold, "
                "consecutive_failures, cron_expression, timezone, created_at, updated_at) VALUES "
                "(:id, :ws, 'owner', 't', '', :a, 'cron', true, '{}', '{}', :threshold, 0, "
                "'0 * * * *', 'UTC', now(), now())"
            ),
            {"id": trigger_id, "ws": workspace_id, "a": uuid4(), "threshold": THRESHOLD},
        )
        await session.commit()
    yield _Setup(maker, workspace_id, trigger_id)
    await engine.dispose()


async def test_failed_runs_disable_the_trigger_and_pause_its_schedule(setup):
    for n in range(1, THRESHOLD + 1):
        task_id = await setup.fired_task()
        await setup.ended(task_id, "task.failed", error="insufficient credits")
        assert await setup.firing_of(task_id) == (
            ExecutionStatus.FAILED.value,
            "insufficient credits",
        )
        assert tuple(await setup.trigger()) == (n, n < THRESHOLD)
    setup.schedules.apply_cron_schedule.assert_awaited_once_with(
        setup.trigger_id, "0 * * * *", "UTC", paused=True
    )


async def test_a_redelivered_failure_counts_once(setup):
    task_id = await setup.fired_task()
    await setup.ended(task_id, "task.failed", error="boom")
    await setup.ended(task_id, "task.failed", error="boom")
    assert tuple(await setup.trigger()) == (1, True)


async def test_a_completed_run_resets_the_count(setup):
    failed = await setup.fired_task()
    await setup.ended(failed, "task.failed", error="boom")
    completed = await setup.fired_task()
    await setup.ended(completed, "task.completed", result="done")
    assert tuple(await setup.trigger()) == (0, True)
    assert (await setup.firing_of(completed)).status == ExecutionStatus.SUCCESS.value


async def test_cancelled_runs_and_other_tasks_do_not_count(setup):
    cancelled = await setup.fired_task()
    await setup.ended(cancelled, "task.cancelled", error="stopped by the user")
    by_a_person = await setup.fired_task(origin_type="user", fired=False)
    await setup.ended(by_a_person, "task.failed", error="boom")
    assert tuple(await setup.trigger()) == (0, True)


async def test_a_failure_before_its_firing_is_recorded_is_retried(setup):
    task_id = await setup.fired_task(fired=False)
    with pytest.raises(FiringNotRecordedError):
        await setup.ended(task_id, "task.failed", error="boom")
    assert tuple(await setup.trigger()) == (0, True)


async def test_a_new_firing_keeps_the_count_its_last_task_left(setup):
    failed = await setup.fired_task()
    await setup.ended(failed, "task.failed", error="boom")
    async with setup.maker() as session:
        service = setup._service(
            session, UserContext(user_id="owner", workspace_id=setup.workspace_id)
        )
        await service.record_execution(
            trigger_id=setup.trigger_id,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=5,
            task_id=uuid4(),
        )
        await session.commit()
    assert tuple(await setup.trigger()) == (1, True)


async def test_the_end_of_a_task_whose_trigger_was_deleted_is_dropped(setup):
    task_id = await setup.fired_task()
    async with setup.maker() as session:
        await session.execute(
            text("DELETE FROM triggers WHERE id = :id"), {"id": setup.trigger_id}
        )
        await session.commit()
    await setup.ended(task_id, "task.failed", error="boom")


async def test_enabling_a_stopped_trigger_starts_its_count_over(setup):
    from agentarea_triggers.infrastructure.repository import TriggerRepository

    for _ in range(THRESHOLD):
        await setup.ended(await setup.fired_task(), "task.failed", error="boom")
    assert tuple(await setup.trigger()) == (THRESHOLD, False)
    async with setup.maker() as session:
        context = UserContext(user_id="owner", workspace_id=setup.workspace_id)
        await TriggerRepository(session, context).enable_trigger(setup.trigger_id)
        await session.commit()
    await setup.ended(await setup.fired_task(), "task.failed", error="boom")
    assert tuple(await setup.trigger()) == (1, True)
