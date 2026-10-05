"""Journal appends against the migrated schema: novelty, ordering, caps.

Set STREAMS_TEST_DATABASE_URL (scripts/check-db.sh does).
"""

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.events.ports import IntegrationEvent
from agentarea_streams.domain import PayloadTooLargeError, StreamKind, StreamQuotaExceededError
from agentarea_streams.domain.keys import event_id_for
from agentarea_streams.infrastructure.journal import StreamJournal
from agentarea_streams.infrastructure.repository import StreamRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")


@pytest.fixture
async def maker():
    engine = create_async_engine(TEST_DATABASE_URL)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _stream(session, ctx):
    with patch(
        "agentarea_common.base.workspace_scoped_repository.grant_resource_owner", new=AsyncMock()
    ):
        stream = await StreamRepository(session, ctx).add_stream(
            name=f"s-{uuid4()}", description="", kind=StreamKind.CUSTOM, retention_days=30
        )
    await session.commit()
    return stream


def _event(data=None, kind="github.push"):
    return IntegrationEvent(type=kind, source="webhook:test", data=data or {"n": 1})


async def test_a_repeated_key_appends_once_and_returns_the_first_sequence(maker):
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session, _scope(ctx):
        stream = await _stream(session, ctx)
        journal = StreamJournal(session, ctx, EventStreamSettings())
        first = await journal.append(stream.id, _event(), event_key="delivery-1")
        await session.commit()
        second = await journal.append(stream.id, _event({"n": 2}), event_key="delivery-1")
        await session.commit()
        assert first.appended and not second.appended
        assert second.sequence == first.sequence
        events = await journal.read_after(stream.id, 0, 10)
        assert [e.data for e in events] == [{"n": 1}]
        assert events[0].id == event_id_for(stream.id, "delivery-1")


async def test_a_repeated_key_is_a_no_op_even_after_the_first_landed_in_another_partition(maker):
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session, _scope(ctx):
        stream = await _stream(session, ctx)
        journal = StreamJournal(session, ctx, EventStreamSettings())
        yesterday = datetime.now(UTC) - timedelta(days=1)
        with patch("agentarea_streams.infrastructure.journal._now", return_value=yesterday):
            await journal.append(stream.id, _event(), event_key="k")
        await session.commit()
        again = await journal.append(stream.id, _event(), event_key="k")
        await session.commit()
        assert not again.appended
        count = await session.execute(
            text("SELECT count(*) FROM stream_events WHERE stream_id = :s"), {"s": stream.id}
        )
        assert count.scalar_one() == 1


async def test_reads_come_back_in_append_order_after_a_cursor(maker):
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session, _scope(ctx):
        stream = await _stream(session, ctx)
        journal = StreamJournal(session, ctx, EventStreamSettings())
        sequences = []
        for i in range(3):
            sequences.append(
                (await journal.append(stream.id, _event({"i": i}), event_key=f"k{i}")).sequence
            )
            await session.commit()
        after_first = await journal.read_after(stream.id, sequences[0], 10)
        assert [e.data["i"] for e in after_first] == [1, 2]
        newest = await journal.read_before(stream.id, None, 2)
        assert [e.data["i"] for e in newest] == [2, 1]
        assert [e.data["i"] for e in await journal.read_before(stream.id, sequences[1], 10)] == [0]
        assert await journal.last_sequence(stream.id) == sequences[2]


async def test_an_oversized_event_is_refused(maker):
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session, _scope(ctx):
        stream = await _stream(session, ctx)
        journal = StreamJournal(session, ctx, EventStreamSettings())
        with pytest.raises(PayloadTooLargeError):
            await journal.append(stream.id, _event({"blob": "x" * (256 * 1024)}), event_key="big")


async def test_the_workspace_quota_is_enforced(maker):
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session, _scope(ctx):
        stream = await _stream(session, ctx)
        journal = StreamJournal(session, ctx, EventStreamSettings(WRITE_QUOTA=2))
        await journal.append(stream.id, _event(), event_key="a")
        await journal.append(stream.id, _event(), event_key="b")
        await session.commit()
        with pytest.raises(StreamQuotaExceededError):
            await journal.append(stream.id, _event(), event_key="c")


class _scope:
    def __init__(self, ctx):
        self._cm = workspace_scope(ctx.workspace_id)

    async def __aenter__(self):
        self._cm.__enter__()

    async def __aexit__(self, *exc):
        self._cm.__exit__(*exc)
