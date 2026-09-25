"""A row the relay performs itself is retried until it succeeds.

Publishing a plain event gives up after ``max_attempts``; that bound keeps a
poisoned event from wedging the loop. A handler row is different: it carries an
effect that has to happen (a removed member's access leaving the graph), and a
graph outage longer than the retry budget -- a restart, a rolling deploy -- would
otherwise end with the relay giving up and the access staying forever. So handler
rows ignore ``max_attempts`` and back off exponentially instead, capped, and say
so loudly once rather than on every attempt.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from agentarea_common.auth import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_common.events.base_events import EventEnvelope
from agentarea_common.events.outbox_orm import EventOutbox
from agentarea_common.events.outbox_relay import OutboxRelay
from agentarea_common.events.outbox_repository import OutboxRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

HANDLED = "test.effect"
PUBLISHED = "test.published"
START = datetime(2026, 9, 25, 12, 0, 0)


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all, tables=[EventOutbox.__table__])
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class Effect:
    def __init__(self) -> None:
        self.failing = True
        self.calls = 0
        self.done = 0

    async def __call__(self, session, envelope) -> None:
        self.calls += 1
        if self.failing:
            raise ConnectionError("graph unavailable")
        self.done += 1


class Broker:
    def __init__(self) -> None:
        self.failing = True

    async def publish(self, envelope) -> None:
        if self.failing:
            raise ConnectionError("broker unavailable")


async def _enqueue(session_factory, event_type: str) -> None:
    async with session_factory() as session:
        await OutboxRepository(session, UserContext(user_id="u", workspace_id="ws")).add(
            EventEnvelope(event_type=event_type, data={}),
            aggregate_id="a",
            aggregate_type="test",
        )
        await session.commit()


async def _row(session_factory, event_type: str) -> EventOutbox:
    async with session_factory() as session:
        return (
            await session.execute(select(EventOutbox).where(EventOutbox.event_type == event_type))
        ).scalar_one()


def _relay(session_factory, effect, clock, broker=None) -> OutboxRelay:
    return OutboxRelay(
        session_factory=session_factory,
        event_broker=broker or Broker(),
        max_attempts=10,
        handlers={HANDLED: effect},
        clock=clock,
    )


async def test_a_handler_row_outlives_the_attempt_budget(session_factory):
    await _enqueue(session_factory, HANDLED)
    effect, clock = Effect(), Clock()
    relay = _relay(session_factory, effect, clock)

    for _ in range(15):
        await relay.process_batch()
        clock.advance(301)
    assert effect.calls == 15

    effect.failing = False
    assert await relay.process_batch() == 1
    assert effect.done == 1
    assert (await _row(session_factory, HANDLED)).published_at is not None


async def test_retries_back_off_exponentially_up_to_a_cap(session_factory):
    await _enqueue(session_factory, HANDLED)
    effect, clock = Effect(), Clock()
    relay = _relay(session_factory, effect, clock)

    delays = []
    for _ in range(12):
        await relay.process_batch()
        row = await _row(session_factory, HANDLED)
        delay = (row.next_attempt_at - clock.now).total_seconds()
        delays.append(delay)
        clock.advance(delay - 0.5)
        calls = effect.calls
        await relay.process_batch()
        assert effect.calls == calls, "a row is not retried before its backoff is over"
        clock.advance(0.5)

    assert delays == [1, 2, 4, 8, 16, 32, 64, 128, 256, 300, 300, 300]


async def test_a_plain_event_keeps_its_attempt_budget_and_no_backoff(session_factory):
    await _enqueue(session_factory, PUBLISHED)
    effect, clock = Effect(), Clock()
    relay = _relay(session_factory, effect, clock)

    for _ in range(12):
        await relay.process_batch()

    row = await _row(session_factory, PUBLISHED)
    assert row.attempts == 10
    assert row.next_attempt_at is None
    assert row.published_at is None


async def test_a_long_outage_is_reported_once(session_factory, caplog):
    await _enqueue(session_factory, HANDLED)
    effect, clock = Effect(), Clock()
    relay = _relay(session_factory, effect, clock)

    with caplog.at_level(logging.WARNING, logger="agentarea_common.events.outbox_relay"):
        for _ in range(30):
            await relay.process_batch()
            clock.advance(301)

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert "20 attempts" in errors[0].getMessage()
