"""Tests for the transactional event outbox: model, repository, publisher, relay.

Uses an in-memory aiosqlite database so the repository CRUD, SKIP-LOCKED
fetch semantics (best-effort on sqlite), and atomicity guarantees can be
exercised without a live Postgres.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from agentarea_common.auth import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_common.events.base_events import DomainEvent, EventEnvelope
from agentarea_common.events.outbox_orm import EventOutbox
from agentarea_common.events.outbox_publisher import OutboxPublisher
from agentarea_common.events.outbox_relay import OutboxRelay
from agentarea_common.events.outbox_repository import OutboxRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    # Create ONLY the outbox table. The full common suite registers other ORM
    # models (e.g. audit_events with a Postgres-only INET column) into the shared
    # BaseModel.metadata, which SQLite cannot compile — so scope create_all to
    # this table instead of the whole metadata.
    async with eng.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all, tables=[EventOutbox.__table__])
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def user_context():
    return UserContext(user_id="user-1", workspace_id="ws-1")


class _TaskUpdated(DomainEvent):
    def __init__(self, task_id: str, status: str) -> None:
        super().__init__(event_type="TaskUpdated", task_id=task_id, status=status)


@pytest.mark.asyncio
async def test_add_inserts_row_and_commits_with_caller(session_factory, user_context):
    """add() writes the row on the caller's session; it persists on commit.

    ``add`` deliberately does NOT commit — the row commits (or rolls back) with
    the caller's unit of work. The rollback half of that contract is asserted in
    ``test_add_is_atomic_with_aggregate_write``.
    """
    async with session_factory() as session:
        repo = OutboxRepository(session, user_context)
        envelope = EventEnvelope.from_any(_TaskUpdated("task-1", "running"))
        await repo.add(envelope, aggregate_id="task-1", aggregate_type="task")
        await session.commit()

    async with session_factory() as verify:
        rows = (await verify.execute(select(EventOutbox))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.event_type == "TaskUpdated"
        assert row.aggregate_id == "task-1"
        assert row.aggregate_type == "task"
        assert row.workspace_id == "ws-1"
        assert row.created_by == "user-1"
        assert row.published_at is None
        assert row.attempts == 0
        assert row.payload["data"]["task_id"] == "task-1"
        assert str(row.event_id) == str(envelope.event_id)


@pytest.mark.asyncio
async def test_add_is_atomic_with_aggregate_write(session_factory, user_context):
    """A failure AFTER enqueue but before commit leaves NO outbox row.

    Models a service op that enqueues the event then raises; the shared txn
    rolls back, so no orphan event is ever published.
    """
    async def _op_that_fails_after_enqueue() -> None:
        async with session_factory() as session:
            repo = OutboxRepository(session, user_context)
            envelope = EventEnvelope.from_any(_TaskUpdated("task-2", "running"))
            await repo.add(envelope, aggregate_id="task-2", aggregate_type="task")
            raise RuntimeError("aggregate write failed after enqueue")

    with pytest.raises(RuntimeError):
        await _op_that_fails_after_enqueue()

    async with session_factory() as verify:
        rows = (await verify.execute(select(EventOutbox))).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_fetch_unpublished_and_mark_published(session_factory, user_context):
    async with session_factory() as session:
        repo = OutboxRepository(session, user_context)
        for i in range(3):
            env = EventEnvelope.from_any(_TaskUpdated(f"task-{i}", "running"))
            await repo.add(env, aggregate_id=f"task-{i}", aggregate_type="task")
        await session.commit()

    async with session_factory() as session:
        repo = OutboxRepository(session, user_context)
        pending = await repo.fetch_unpublished(limit=10)
        assert len(pending) == 3
        await repo.mark_published(pending[0].id)
        await session.commit()

    async with session_factory() as session:
        repo = OutboxRepository(session, user_context)
        pending = await repo.fetch_unpublished(limit=10)
        assert len(pending) == 2


@pytest.mark.asyncio
async def test_mark_failed_records_error_and_increments_attempts(session_factory, user_context):
    async with session_factory() as session:
        repo = OutboxRepository(session, user_context)
        env = EventEnvelope.from_any(_TaskUpdated("task-x", "running"))
        await repo.add(env, aggregate_id="task-x", aggregate_type="task")
        await session.commit()
        row_id = (await repo.fetch_unpublished(limit=1))[0].id

    async with session_factory() as session:
        repo = OutboxRepository(session, user_context)
        await repo.mark_failed(row_id, "boom")
        await session.commit()

    async with session_factory() as verify:
        row = (await verify.execute(select(EventOutbox).where(EventOutbox.id == row_id))).scalar_one()
        assert row.attempts == 1
        assert row.last_error == "boom"
        assert row.published_at is None  # failed rows stay unpublished for retry


@pytest.mark.asyncio
async def test_publisher_derives_aggregate_and_enqueues(session_factory, user_context):
    async with session_factory() as session:
        publisher = OutboxPublisher(session, user_context)
        await publisher.publish(_TaskUpdated("task-9", "completed"))
        await session.commit()

    async with session_factory() as verify:
        row = (await verify.execute(select(EventOutbox))).scalar_one()
        assert row.aggregate_id == "task-9"
        assert row.aggregate_type == "task"


class _FakeBroker:
    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.published: list[EventEnvelope] = []
        self._fail_on = fail_on or set()

    async def publish(self, event) -> None:
        envelope = EventEnvelope.from_any(event)
        if envelope.data.get("task_id") in self._fail_on:
            raise RuntimeError("broker down")
        self.published.append(envelope)


@pytest.mark.asyncio
async def test_relay_publishes_then_marks_published(session_factory, user_context):
    async with session_factory() as session:
        repo = OutboxRepository(session, user_context)
        env = EventEnvelope.from_any(_TaskUpdated("task-relay", "running"))
        await repo.add(env, aggregate_id="task-relay", aggregate_type="task")
        await session.commit()

    broker = _FakeBroker()
    relay = OutboxRelay(session_factory=session_factory, event_broker=broker, batch_size=10)
    processed = await relay.process_batch()

    assert processed == 1
    assert len(broker.published) == 1
    assert broker.published[0].data["task_id"] == "task-relay"

    async with session_factory() as verify:
        row = (await verify.execute(select(EventOutbox))).scalar_one()
        assert row.published_at is not None


@pytest.mark.asyncio
async def test_relay_publish_failure_marks_failed_not_lost(session_factory, user_context):
    async with session_factory() as session:
        repo = OutboxRepository(session, user_context)
        env = EventEnvelope.from_any(_TaskUpdated("task-fail", "running"))
        await repo.add(env, aggregate_id="task-fail", aggregate_type="task")
        await session.commit()

    broker = _FakeBroker(fail_on={"task-fail"})
    relay = OutboxRelay(session_factory=session_factory, event_broker=broker, batch_size=10)
    processed = await relay.process_batch()

    assert processed == 0
    assert broker.published == []

    async with session_factory() as verify:
        row = (await verify.execute(select(EventOutbox))).scalar_one()
        assert row.published_at is None  # still pending — not lost
        assert row.attempts == 1
        assert row.last_error is not None

    # Next pass with a healthy broker delivers it (retry, not dropped).
    healthy = _FakeBroker()
    relay2 = OutboxRelay(session_factory=session_factory, event_broker=healthy, batch_size=10)
    processed2 = await relay2.process_batch()
    assert processed2 == 1
    assert len(healthy.published) == 1
