"""The feed's catch-up read against the migrated task log.

A day-long task has tens of thousands of rows, and every reconnect used to fetch
all of them in one query. The snapshot reads the log's feed rows (event rows and
the messages a person sent) in bounded batches in ``seq`` order, and a
reconnecting client resumes after the last ``seq`` it saw. Ordering and the
workspace filter are Postgres semantics a mocked session cannot check.

Set TASKS_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from agentarea_api.api.v1 import task_event_feed
from agentarea_common.auth.context import UserContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("TASKS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TASKS_TEST_DATABASE_URL not set")

_T0 = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


@pytest.fixture
async def db(monkeypatch):
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    opened: list[int] = []

    @asynccontextmanager
    async def get_db_session():
        opened.append(1)
        async with maker() as session:
            yield session

    monkeypatch.setattr("agentarea_api.api.deps.database.get_db_session", get_db_session)
    workspace_id, task_id = str(uuid4()), str(uuid4())
    try:
        yield maker, workspace_id, task_id, opened
    finally:
        async with maker() as session:
            await session.execute(
                text("DELETE FROM task_conversation_entries WHERE workspace_id = ANY(:ws)"),
                {"ws": [workspace_id, f"other-{workspace_id}"]},
            )
            await session.commit()
        await engine.dispose()


async def _insert(
    maker,
    *,
    workspace_id: str,
    task_id: str,
    seq: int,
    kind: str = "event",
    role: str = "event",
    name: str | None = "tool.result",
) -> str:
    event_id = uuid4()
    async with maker() as session:
        await session.execute(
            text(
                "INSERT INTO task_conversation_entries "
                "(id, task_id, seq, event_id, kind, role, content, name, meta, created_at, "
                "workspace_id, created_by) VALUES (gen_random_uuid(), :task_id, :seq, :event_id, "
                ":kind, :role, :content, :name, CAST(:meta AS jsonb), :ts, :ws, 'writer')"
            ),
            {
                "task_id": UUID(task_id),
                "seq": seq,
                "event_id": event_id,
                "kind": kind,
                "role": role,
                "content": f"text {seq}",
                "name": name,
                "meta": json.dumps({"n": seq}),
                "ts": _T0 + timedelta(seconds=seq),
                "ws": workspace_id,
            },
        )
        await session.commit()
    return str(event_id)


def _reader(workspace_id: str) -> UserContext:
    return UserContext(user_id="reader", workspace_id=workspace_id)


async def _ids(snapshot) -> list[str]:
    return [env.event_id async for env in snapshot]


async def test_snapshot_is_the_feed_rows_in_bounded_batches_in_seq_order(db):
    maker, workspace_id, task_id, opened = db
    expected = [
        await _insert(maker, workspace_id=workspace_id, task_id=task_id, seq=0),
        await _insert(
            maker,
            workspace_id=workspace_id,
            task_id=task_id,
            seq=1,
            kind="message",
            role="user",
            name=None,
        ),
    ]
    await _insert(
        maker,
        workspace_id=workspace_id,
        task_id=task_id,
        seq=2,
        kind="message",
        role="assistant",
        name=None,
    )
    expected += [
        await _insert(maker, workspace_id=workspace_id, task_id=task_id, seq=seq)
        for seq in (3, 4, 5)
    ]
    await _insert(maker, workspace_id=f"other-{workspace_id}", task_id=task_id, seq=6)
    opened.clear()

    snapshot = [
        env
        async for env in task_event_feed._iter_snapshot(
            task_id, _reader(workspace_id), batch_size=2
        )
    ]

    assert [env.event_id for env in snapshot] == expected
    assert [env.event_type for env in snapshot][:2] == ["tool.result", "message.received"]
    assert snapshot[1].data["content"] == "text 1"
    # Two full batches, then the short one that ends the snapshot.
    assert len(opened) == 3


async def test_resumed_snapshot_starts_after_the_position_seen(db):
    maker, workspace_id, task_id, _ = db
    ids = [
        await _insert(maker, workspace_id=workspace_id, task_id=task_id, seq=seq)
        for seq in range(4)
    ]

    cursor = await task_event_feed._load_cursor(task_id, _reader(workspace_id), "1")
    assert cursor is not None
    assert cursor.seq == 1
    resumed = await _ids(
        task_event_feed._iter_snapshot(task_id, _reader(workspace_id), cursor, batch_size=1)
    )

    assert resumed == ids[2:]


async def test_a_cursor_from_another_workspace_or_malformed_is_not_found(db):
    maker, workspace_id, task_id, _ = db
    await _insert(maker, workspace_id=f"other-{workspace_id}", task_id=task_id, seq=0)

    assert await task_event_feed._load_cursor(task_id, _reader(workspace_id), "0") is None
    assert await task_event_feed._load_cursor(task_id, _reader(workspace_id), "not-a-seq") is None
