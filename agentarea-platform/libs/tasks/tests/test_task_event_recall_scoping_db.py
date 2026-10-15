"""Real migrated PostgreSQL coverage for recalling one task's events by type.

The agent's ``recall_history`` tool reads events of a type to recover context
that was compacted out of its working set. Those payloads carry message content
and tool results, so a recall filtered on workspace alone hands one task the
transcript of every other task in the workspace.

Set TASKS_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database.
"""

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_tasks.application.task_event_service import TaskEventService
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("TASKS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TASKS_TEST_DATABASE_URL not set")


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


def _service(session: AsyncSession, workspace_id: str) -> TaskEventService:
    user_context = UserContext(user_id="event-writer", workspace_id=workspace_id)
    return TaskEventService(RepositoryFactory(session, user_context), event_broker=None)


async def _record(
    service: TaskEventService, workspace_id: str, task_id: UUID, at: datetime, text: str
) -> None:
    await service.create_workflow_event(
        task_id=task_id,
        event_id=uuid4(),
        event_type="tool.result",
        data={"text": text},
        timestamp=at,
        workspace_id=workspace_id,
        created_by="event-writer",
    )


async def test_recall_by_type_returns_only_the_recalling_tasks_events(session):
    workspace_id, own_task, other_task = str(uuid4()), uuid4(), uuid4()
    service = _service(session, workspace_id)
    start = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    await _record(service, workspace_id, own_task, start, "own")
    await _record(service, workspace_id, other_task, start + timedelta(seconds=1), "foreign")

    recalled = await service.get_events_by_type(task_id=own_task, event_type="tool.result")

    assert [event.data["text"] for event in recalled] == ["own"]
    assert {event.task_id for event in recalled} == {own_task}
