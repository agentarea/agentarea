"""A poisoned event must not wedge the relay.

The relay module promises exactly this: "Rows that exceed max_attempts are
logged loudly and skipped so a permanently poisoned event cannot wedge the
loop." Skipping them in the loop is not enough — they are never marked
published, so they stay the OLDEST unpublished rows forever. Once enough of
them accumulate to fill a batch, every fetch returns only poisoned rows, every
one is skipped, and no live event is ever published again.

The bound therefore belongs in the query, not in the loop.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from agentarea_common.auth import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_common.events.base_events import DomainEvent, EventEnvelope
from agentarea_common.events.outbox_orm import EventOutbox
from agentarea_common.events.outbox_relay import OutboxRelay
from agentarea_common.events.outbox_repository import OutboxRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
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
    def __init__(self, task_id: str) -> None:
        super().__init__(event_type="TaskUpdated", task_id=task_id)


class _CapturingBroker:
    def __init__(self) -> None:
        self.published: list[str] = []

    async def publish(self, envelope) -> None:
        self.published.append(envelope.data.get("task_id"))


async def _enqueue(session_factory, user_context, task_id: str, attempts: int = 0) -> None:
    async with session_factory() as session:
        repo = OutboxRepository(session, user_context)
        row = await repo.add(
            EventEnvelope.from_any(_TaskUpdated(task_id)),
            aggregate_id=task_id,
            aggregate_type="task",
        )
        row.attempts = attempts
        await session.commit()


@pytest.mark.asyncio
async def test_exhausted_rows_are_not_fetched(session_factory, user_context):
    await _enqueue(session_factory, user_context, "poisoned", attempts=5)
    await _enqueue(session_factory, user_context, "fresh", attempts=0)

    async with session_factory() as session:
        repo = OutboxRepository(session, user_context)
        rows = await repo.fetch_unpublished(limit=10, max_attempts=5)

    assert [r.aggregate_id for r in rows] == ["fresh"]


@pytest.mark.asyncio
async def test_a_batch_of_poisoned_rows_does_not_starve_live_events(
    session_factory, user_context
):
    # The wedge: poisoned rows are the oldest, so they fill the batch first and
    # a live event queued behind them can never be reached.
    batch_size = 3
    for i in range(batch_size):
        await _enqueue(session_factory, user_context, f"poisoned-{i}", attempts=5)
    await _enqueue(session_factory, user_context, "live", attempts=0)

    broker = _CapturingBroker()
    relay = OutboxRelay(
        session_factory=session_factory,
        event_broker=broker,
        batch_size=batch_size,
        max_attempts=5,
    )

    published = await relay.process_batch()

    assert published == 1, "the live event must still be delivered"
    assert broker.published == ["live"]


@pytest.mark.asyncio
async def test_rows_below_the_bound_are_still_retried(session_factory, user_context):
    await _enqueue(session_factory, user_context, "retryable", attempts=4)

    broker = _CapturingBroker()
    relay = OutboxRelay(
        session_factory=session_factory,
        event_broker=broker,
        batch_size=10,
        max_attempts=5,
    )

    assert await relay.process_batch() == 1
    assert broker.published == ["retryable"]
