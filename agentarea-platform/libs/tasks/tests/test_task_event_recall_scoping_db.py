"""Real migrated PostgreSQL coverage for recalling one task's events by type.

The agent's ``recall_history`` tool reads events of a type to recover context
that was compacted out of its working set. Those payloads carry message content
and tool results, so a recall filtered on workspace alone hands one task the
transcript of every other task in the workspace.

Set TASKS_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database.
"""

import os
from uuid import UUID, uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_tasks.infrastructure.task_log import TaskFeedReader
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


async def _record(session: AsyncSession, workspace_id: str, task_id: UUID, seq: int, note: str):
    await session.execute(
        text(
            "INSERT INTO task_conversation_entries "
            "(id, task_id, seq, event_id, kind, role, content, name, meta, workspace_id, "
            "created_by) VALUES (gen_random_uuid(), :task_id, :seq, :event_id, 'event', "
            "'event', '', 'tool.result', CAST(:meta AS jsonb), :ws, 'event-writer')"
        ),
        {
            "task_id": task_id,
            "seq": seq,
            "event_id": uuid4(),
            "meta": f'{{"text": "{note}"}}',
            "ws": workspace_id,
        },
    )


async def test_recall_by_type_returns_only_the_recalling_tasks_events(session):
    workspace_id, own_task, other_task = str(uuid4()), uuid4(), uuid4()
    await _record(session, workspace_id, own_task, 0, "own")
    await _record(session, workspace_id, other_task, 0, "foreign")
    reader = TaskFeedReader(session, UserContext(user_id="reader", workspace_id=workspace_id))

    recalled = await reader.latest_of_types(own_task, ["tool.result"], limit=20)

    assert [entry.meta["text"] for entry in recalled] == ["own"]
