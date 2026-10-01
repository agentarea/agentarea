"""Real migrated PostgreSQL coverage for idempotent task-event persistence.

The workflow-event activity is retried as a whole batch, so storing an event
must be keyed by the id the workflow minted: a retry returns the stored row
instead of inserting a copy. Only the primary key on the migrated table can
prove that; a mocked session accepts any number of inserts.

Set TASKS_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database.
"""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_tasks.application.task_event_service import TaskEventService
from sqlalchemy import text
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


async def _rows(session: AsyncSession, event_id) -> list:
    result = await session.execute(
        text("SELECT id, workspace_id, timestamp FROM task_events WHERE id = :id"),
        {"id": event_id},
    )
    return list(result.fetchall())


async def test_retried_event_is_stored_once_with_the_workflow_identity(session):
    workspace_id, task_id, event_id = str(uuid4()), uuid4(), uuid4()
    minted_at = datetime(2026, 9, 29, 12, 0, 0, 123456, tzinfo=UTC)
    service = _service(session, workspace_id)

    stored = [
        await service.create_workflow_event(
            task_id=task_id,
            event_id=event_id,
            event_type="tool.result",
            data={"attempt": attempt},
            timestamp=minted_at,
            workspace_id=workspace_id,
            created_by="event-writer",
        )
        for attempt in (1, 2)
    ]

    assert [event.id for event in stored] == [event_id, event_id]
    assert [event.timestamp for event in stored] == [minted_at, minted_at]
    # The retry returns what the first attempt stored, not its own payload.
    assert [event.data for event in stored] == [{"attempt": 1}, {"attempt": 1}]
    rows = await _rows(session, event_id)
    assert len(rows) == 1
    assert rows[0].timestamp == minted_at


async def test_an_event_id_taken_in_another_workspace_is_refused(session):
    owner_ws, other_ws, task_id, event_id = str(uuid4()), str(uuid4()), uuid4(), uuid4()
    minted_at = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    await _service(session, owner_ws).create_workflow_event(
        task_id=task_id,
        event_id=event_id,
        event_type="tool.result",
        data={},
        timestamp=minted_at,
        workspace_id=owner_ws,
        created_by="event-writer",
    )

    with pytest.raises(ValueError, match="already stored"):
        await _service(session, other_ws).create_workflow_event(
            task_id=task_id,
            event_id=event_id,
            event_type="tool.result",
            data={},
            timestamp=minted_at,
            workspace_id=other_ws,
            created_by="event-writer",
        )

    assert [row.workspace_id for row in await _rows(session, event_id)] == [owner_ws]
