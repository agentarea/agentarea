"""A schedule does not start a run while the trigger's last one is still going, against the migrated schema.

The schedule's own overlap policy sees only the firing workflow, which ends as
soon as the task is started. Set STREAMS_TEST_DATABASE_URL.
"""

import os
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_triggers.trigger_service import TriggerService
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")


class _Temporal:
    """Which agent workflows are still open; the rest closed or were never known."""

    def __init__(self) -> None:
        self.open: set[str] = set()

    async def workflow_is_open(self, workflow_id: str) -> bool:
        return workflow_id in self.open


class _Setup:
    def __init__(self, maker, workspace_id: str):
        self.maker = maker
        self.workspace_id = workspace_id
        self.started: list[UUID] = []
        self.temporal = _Temporal()

    async def trigger(self, trigger_type: str = "cron") -> UUID:
        trigger_id, agent_id = uuid4(), uuid4()
        async with self.maker() as session:
            await session.execute(
                text(
                    "INSERT INTO agents (id, workspace_id, created_by, name, slug, status) "
                    "VALUES (:id, :ws, 'owner', 'Inbox clerk', :slug, 'active')"
                ),
                {"id": agent_id, "ws": self.workspace_id, "slug": f"clerk-{agent_id.hex[:8]}"},
            )
            await session.execute(
                text(
                    "INSERT INTO triggers (id, workspace_id, created_by, name, description, "
                    "agent_id, trigger_type, is_active, task_parameters, conditions, "
                    "failure_threshold, consecutive_failures, cron_expression, timezone, "
                    "created_at, updated_at) VALUES (:id, :ws, 'owner', 't', '', :a, :type, "
                    "true, '{\"text\": \"Sort the inbox\"}', '{}', 5, 0, '*/15 * * * *', 'UTC', "
                    "now(), now())"
                ),
                {"id": trigger_id, "ws": self.workspace_id, "a": agent_id, "type": trigger_type},
            )
            await session.commit()
        return trigger_id

    async def task(
        self, status: str, origin_id: UUID | None, *, run: str = "open"
    ) -> UUID:
        """A task with its workflow ``open``, ``closed`` or ``none`` (never started)."""
        task_id = uuid4()
        workflow_id = None if run == "none" else f"agent-task-{task_id}"
        if run == "open":
            self.temporal.open.add(workflow_id)
        async with self.maker() as session:
            await session.execute(
                text(
                    "INSERT INTO tasks (id, agent_id, description, status, workspace_id, "
                    "created_by, origin_type, origin_id, execution_id) VALUES (:id, :agent, "
                    "'d', :status, :ws, 'owner', :origin_type, :origin_id, :execution_id)"
                ),
                {
                    "id": task_id,
                    "agent": uuid4(),
                    "status": status,
                    "ws": self.workspace_id,
                    "origin_type": "trigger" if origin_id else "user",
                    "origin_id": str(origin_id) if origin_id else None,
                    "execution_id": workflow_id,
                },
            )
            await session.commit()
        return task_id

    async def fire(self, trigger_id: UUID, fired_by: str | None = None):
        async def submit(task, **_):
            task.status = "running"
            task.execution_id = f"agent-task-{task.id}"
            self.temporal.open.add(task.execution_id)
            self.started.append(task.id)
            async with self.maker() as stored:
                await stored.execute(
                    text(
                        "INSERT INTO tasks (id, agent_id, description, status, workspace_id, "
                        "created_by, origin_type, origin_id, execution_id) VALUES (:id, :agent, "
                        "'d', 'running', :ws, 'owner', :origin_type, :origin_id, :execution_id)"
                    ),
                    {
                        "id": task.id,
                        "agent": task.agent_id,
                        "ws": self.workspace_id,
                        "origin_type": task.provenance.origin_type,
                        "origin_id": task.provenance.origin_id,
                        "execution_id": task.execution_id,
                    },
                )
                await stored.commit()
            return task

        task_service = AsyncMock()
        task_service.route_or_submit_task.side_effect = submit
        async with self.maker() as session:
            service = TriggerService(
                repository_factory=RepositoryFactory(
                    session, UserContext(user_id="owner", workspace_id=self.workspace_id)
                ),
                event_broker=AsyncMock(),
                task_service=task_service,
                temporal_schedule_manager=self.temporal,  # type: ignore[arg-type]
            )
            firing = await service.fire(trigger_id, {"source": "cron"}, fired_by)
            await session.commit()
        return firing


@pytest.fixture
async def setup():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield _Setup(maker, str(uuid4()))
    await engine.dispose()


async def test_a_scheduled_firing_skips_while_the_last_run_is_still_going(setup):
    trigger_id = await setup.trigger()
    running = await setup.task("waiting_for_approval", trigger_id)

    firing = await setup.fire(trigger_id)

    assert firing.outcome == "skipped"
    assert firing.blocked_by == running
    assert str(running) in (firing.execution.error_message or "")
    assert setup.started == []


async def test_a_scheduled_firing_starts_once_the_last_run_ended(setup):
    trigger_id = await setup.trigger()
    for status in ("completed", "failed", "cancelled", "blocked"):
        await setup.task(status, trigger_id)

    firing = await setup.fire(trigger_id)

    assert firing.outcome == "reacted"
    assert setup.started == [firing.task_id]


async def test_a_status_that_outlived_its_run_does_not_hold_the_schedule_back(setup):
    """A terminated workflow, a lost history or a failed status write leaves a task 'running'."""
    trigger_id = await setup.trigger()
    await setup.task("running", trigger_id, run="closed")
    await setup.task("pending", trigger_id, run="none")

    assert (await setup.fire(trigger_id)).outcome == "reacted"


async def test_runs_of_other_triggers_and_people_do_not_hold_a_schedule_back(setup):
    trigger_id = await setup.trigger()
    await setup.task("running", await setup.trigger())
    await setup.task("running", None)

    assert (await setup.fire(trigger_id)).outcome == "reacted"


async def test_a_person_running_the_trigger_is_not_held_back(setup):
    trigger_id = await setup.trigger()
    await setup.task("running", trigger_id)

    assert (await setup.fire(trigger_id, fired_by="person")).outcome == "reacted"


async def test_a_run_a_person_started_holds_the_schedule_back_too(setup):
    trigger_id = await setup.trigger()
    by_hand = await setup.fire(trigger_id, fired_by="person")

    firing = await setup.fire(trigger_id)

    assert (firing.outcome, firing.blocked_by) == ("skipped", by_hand.task_id)


async def test_an_event_trigger_runs_every_event(setup):
    trigger_id = await setup.trigger("stream")
    await setup.task("running", trigger_id)

    assert (await setup.fire(trigger_id)).outcome == "reacted"
