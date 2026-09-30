"""The SSE catch-up read against the migrated ``task_events`` table.

A day-long task has tens of thousands of rows, and every reconnect used to
fetch all of them in one query. The snapshot is now read in bounded keyset
batches ordered by ``(timestamp, id)``, and a reconnecting client resumes after
the last event it saw. Keyset order and the row comparison are Postgres
semantics a mocked session cannot check.

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
                text("DELETE FROM task_events WHERE workspace_id = ANY(:ws)"),
                {"ws": [workspace_id, f"other-{workspace_id}"]},
            )
            await session.commit()
        await engine.dispose()


async def _insert(maker, *, workspace_id: str, task_id: str, event_id: UUID, seconds: int) -> str:
    async with maker() as session:
        await session.execute(
            text(
                "INSERT INTO task_events "
                "(id, task_id, event_type, timestamp, data, event_metadata, workspace_id, "
                "created_by) VALUES (:id, :task_id, 'tool.result', :ts, "
                "CAST(:data AS jsonb), '{}'::jsonb, :ws, 'writer')"
            ),
            {
                "id": event_id,
                "task_id": UUID(task_id),
                "ts": _T0 + timedelta(seconds=seconds),
                "data": json.dumps({"n": seconds}),
                "ws": workspace_id,
            },
        )
        await session.commit()
    return str(event_id)


async def _ids(snapshot) -> list[str]:
    return [env.event_id async for env in snapshot]


async def test_snapshot_is_read_in_bounded_batches_in_keyset_order(db):
    maker, workspace_id, task_id, opened = db
    # Two rows share a timestamp: the id breaks the tie so no row is skipped
    # or repeated at a batch boundary.
    tie_ids = sorted([uuid4(), uuid4()], key=str)
    expected = [
        await _insert(
            maker, workspace_id=workspace_id, task_id=task_id, event_id=uuid4(), seconds=s
        )
        for s in range(3)
    ]
    for event_id in tie_ids:
        expected.append(
            await _insert(
                maker, workspace_id=workspace_id, task_id=task_id, event_id=event_id, seconds=3
            )
        )
    expected.append(
        await _insert(
            maker, workspace_id=workspace_id, task_id=task_id, event_id=uuid4(), seconds=4
        )
    )
    await _insert(
        maker, workspace_id=f"other-{workspace_id}", task_id=task_id, event_id=uuid4(), seconds=1
    )
    opened.clear()

    ids = await _ids(task_event_feed._iter_snapshot(task_id, workspace_id, batch_size=2))

    assert ids == expected
    # Three full batches, then the empty read that ends the snapshot.
    assert len(opened) == 4


async def test_resumed_snapshot_starts_after_the_last_event_seen(db):
    maker, workspace_id, task_id, _ = db
    tie_ids = sorted([uuid4(), uuid4()], key=str)
    first = await _insert(
        maker, workspace_id=workspace_id, task_id=task_id, event_id=uuid4(), seconds=0
    )
    tied = [
        await _insert(maker, workspace_id=workspace_id, task_id=task_id, event_id=e, seconds=1)
        for e in tie_ids
    ]
    last = await _insert(
        maker, workspace_id=workspace_id, task_id=task_id, event_id=uuid4(), seconds=2
    )

    cursor = await task_event_feed._load_cursor(task_id, workspace_id, tied[0])
    assert cursor is not None
    ids = await _ids(task_event_feed._iter_snapshot(task_id, workspace_id, cursor, batch_size=1))

    assert first not in ids
    assert ids == [tied[1], last]


async def test_a_cursor_from_another_workspace_or_malformed_is_not_found(db):
    maker, workspace_id, task_id, _ = db
    foreign = await _insert(
        maker, workspace_id=f"other-{workspace_id}", task_id=task_id, event_id=uuid4(), seconds=0
    )

    assert await task_event_feed._load_cursor(task_id, workspace_id, foreign) is None
    assert await task_event_feed._load_cursor(task_id, workspace_id, "not-a-uuid") is None
