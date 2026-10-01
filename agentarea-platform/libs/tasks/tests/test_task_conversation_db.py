"""Real migrated PostgreSQL coverage for a task's model conversation log.

The workflow assigns each entry its position and a retried activity writes the
same positions again, so a write must replace, never duplicate; the model's
window is the head entries in their order plus the tail range. Only the unique
constraint and the ordering of the migrated table can prove that.

Set TASKS_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database.
"""

import os
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_tasks.domain.models import ConversationEntry
from agentarea_tasks.infrastructure.repository import TaskConversationRepository
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


def _repository(session: AsyncSession, workspace_id: str) -> TaskConversationRepository:
    return TaskConversationRepository(
        session, UserContext(user_id="conversation-writer", workspace_id=workspace_id)
    )


def _entry(seq: int, content: str, **fields) -> ConversationEntry:
    return ConversationEntry(seq=seq, role=fields.pop("role", "user"), content=content, **fields)


async def test_rewriting_a_position_replaces_the_entry(session):
    task_id, workspace_id = uuid4(), str(uuid4())
    repository = _repository(session, workspace_id)

    await repository.write(task_id, [_entry(0, "system", role="system"), _entry(1, "first")])
    await repository.write(task_id, [_entry(1, "first, retried"), _entry(2, "second")])

    count = await session.scalar(
        text("SELECT count(*) FROM task_conversation_entries WHERE task_id = :task_id"),
        {"task_id": task_id},
    )
    head, tail = await repository.read(task_id, head_seqs=[0], tail_start=1, end_seq=3)
    assert count == 3
    assert [entry.content for entry in (*head, *tail)] == ["system", "first, retried", "second"]


async def test_the_window_is_the_head_in_order_then_the_tail_range(session):
    task_id, workspace_id = uuid4(), str(uuid4())
    repository = _repository(session, workspace_id)
    await repository.write(
        task_id,
        [
            _entry(0, "system", role="system"),
            *(_entry(seq, f"turn {seq}") for seq in range(1, 6)),
            _entry(6, "summary of 1-3", kind="summary"),
            _entry(7, "after the bound"),
        ],
    )

    head, tail = await repository.read(task_id, head_seqs=[0, 6], tail_start=4, end_seq=7)

    assert [entry.seq for entry in head] == [0, 6]
    assert [entry.seq for entry in tail] == [4, 5]
    assert head[1].kind == "summary"


async def test_another_workspace_cannot_read_or_overwrite_the_log(session):
    task_id = uuid4()
    owner, stranger = _repository(session, str(uuid4())), _repository(session, str(uuid4()))
    await owner.write(task_id, [_entry(0, "system", role="system"), _entry(1, "secret")])

    await stranger.write(task_id, [_entry(1, "overwritten")])

    with pytest.raises(LookupError):
        await stranger.read(task_id, head_seqs=[0], tail_start=1, end_seq=2)
    _, tail = await owner.read(task_id, head_seqs=[0], tail_start=1, end_seq=2)
    assert [entry.content for entry in tail] == ["secret"]
