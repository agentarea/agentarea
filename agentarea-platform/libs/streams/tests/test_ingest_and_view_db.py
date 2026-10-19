"""Ingest onto the bus and the events read model, against the migrated schema.

Ingest names the event deterministically and publishes it once; the quota
counts what the read model received in the last minute. The events view writes
each event once, whatever the broker redelivers. Set STREAMS_TEST_DATABASE_URL.
"""

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import tenant_scoped_session_class, workspace_scope
from agentarea_common.broker.topics import stream_events_partition
from agentarea_common.config.database import TenantScopeMode
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.events.ports import IntegrationEvent
from agentarea_streams.application.events_view import EventsView
from agentarea_streams.application.ingest import StreamIngest
from agentarea_streams.domain import (
    StreamEvent,
    StreamKind,
    StreamNotFoundError,
    StreamQuotaExceededError,
)
from agentarea_streams.domain.keys import event_id_for
from agentarea_streams.infrastructure.bus import StreamBus
from agentarea_streams.infrastructure.event_repository import StreamEventRepository
from agentarea_streams.infrastructure.repository import StreamRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")
GRANT = "agentarea_common.base.workspace_scoped_repository.grant_resource_owner"


class _Publisher:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.published: list[tuple[str, IntegrationEvent]] = []

    async def publish(self, event, *, topic=None):
        if self.fail:
            raise ConnectionError("broker down")
        self.published.append((topic, event))


class _Dedup:
    def __init__(self):
        self.keys: set[str] = set()

    async def claim(self, key):
        if key in self.keys:
            return False
        self.keys.add(key)
        return True

    async def release(self, key):
        self.keys.discard(key)


@pytest.fixture
async def maker():
    engine = create_async_engine(TEST_DATABASE_URL)
    yield async_sessionmaker(
        engine,
        class_=AsyncSession,
        sync_session_class=tenant_scoped_session_class(TenantScopeMode.ENFORCE),
        expire_on_commit=False,
    )
    await engine.dispose()


@pytest.fixture
def ctx():
    context = UserContext(user_id="u", workspace_id=str(uuid4()))
    with workspace_scope(context.workspace_id):
        yield context


async def _stream(session, ctx):
    with patch(GRANT, new=AsyncMock()):
        stream = await StreamRepository(session, ctx).add_stream(
            name=f"s-{uuid4()}", description="", kind=StreamKind.CUSTOM
        )
    await session.commit()
    return stream


def _event(data=None, kind="github.push"):
    return IntegrationEvent(type=kind, source="webhook:test", data=data or {"n": 1})


class _Notices:
    def __init__(self):
        self.recorded_ids: list = []

    async def recorded(self, event):
        self.recorded_ids.append(event.id)

    async def processing(self, event):
        raise AssertionError("the events view announces arrivals only")


class _Quota:
    """The sliding-minute quota as Redis keeps it, without the clock: a count per workspace."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def take(self, workspace_id, limit, now):
        if self.counts.get(workspace_id, 0) + 1 > limit:
            return False
        self.counts[workspace_id] = self.counts.get(workspace_id, 0) + 1
        return True


def _ingest(session, ctx, publisher, dedup, settings=None):
    bus = StreamBus(publisher=publisher, dedup=dedup, quota=_Quota(), partitions=16)
    return StreamIngest(session, ctx, settings or EventStreamSettings(), bus)


async def test_an_event_goes_to_its_stream_topic_named_by_its_key(maker, ctx):
    publisher, dedup = _Publisher(), _Dedup()
    async with maker() as session:
        stream = await _stream(session, ctx)
        ingest = _ingest(session, ctx, publisher, dedup)
        first = await ingest.append(stream.id, _event(), event_key="delivery-1", source_id=None)
        again = await ingest.append(stream.id, _event({"n": 2}), event_key="delivery-1")
    assert first.appended
    assert not again.appended
    assert first.event_id == again.event_id == event_id_for(stream.id, "delivery-1")
    [(topic, message)] = publisher.published
    assert topic == stream_events_partition(stream.id, 16)
    carried = StreamEvent.from_bus(message)
    assert carried.id == first.event_id
    assert carried.stream_id == stream.id
    assert carried.workspace_id == ctx.workspace_id
    assert carried.event_key == "delivery-1"


async def test_a_failed_publish_leaves_the_event_free_for_the_sender_s_retry(maker, ctx):
    publisher, dedup = _Publisher(fail=True), _Dedup()
    async with maker() as session:
        stream = await _stream(session, ctx)
        with pytest.raises(ConnectionError):
            await _ingest(session, ctx, publisher, dedup).append(stream.id, _event(), event_key="k")
        publisher.fail = False
        retried = await _ingest(session, ctx, publisher, dedup).append(
            stream.id, _event(), event_key="k"
        )
    assert retried.appended


async def test_a_large_event_is_carried_and_a_foreign_one_refused(maker, ctx):
    async with maker() as session:
        stream = await _stream(session, ctx)
        ingest = _ingest(session, ctx, _Publisher(), _Dedup())
        large = await ingest.append(stream.id, _event({"blob": "x" * (256 * 1024)}), event_key="b")
        assert large.appended
        with pytest.raises(StreamNotFoundError):
            await ingest.append(uuid4(), _event(), event_key="k")


async def test_the_workspace_quota_counts_each_admitted_event_before_the_view_sees_it(maker, ctx):
    async with maker() as session:
        stream = await _stream(session, ctx)
        ingest = _ingest(session, ctx, _Publisher(), _Dedup(), EventStreamSettings(WRITE_QUOTA=2))
        for key in ("a", "b"):
            await ingest.append(stream.id, _event(), event_key=key)
        with pytest.raises(StreamQuotaExceededError):
            await ingest.append(stream.id, _event(), event_key="c")


def _stream_event(stream_id, ctx, key, received_at=None):
    return StreamEvent(
        id=event_id_for(stream_id, key),
        type="push",
        source="test",
        data={"key": key},
        stream_id=stream_id,
        workspace_id=ctx.workspace_id,
        created_by=ctx.user_id,
        event_key=key,
        received_at=received_at or datetime.now(UTC),
    )


async def test_the_view_writes_a_redelivered_event_once_even_across_days(maker, ctx):
    async with maker() as session:
        stream = await _stream(session, ctx)
    event = _stream_event(stream.id, ctx, "k")
    notices = _Notices()
    view = EventsView(maker, notices)
    await view.handle(event.to_bus())
    await view.handle(event.to_bus())
    yesterday = event.model_copy(update={"received_at": datetime.now(UTC) - timedelta(days=1)})
    await view.handle(yesterday.to_bus())
    async with maker() as session:
        events = await StreamEventRepository(session, ctx).read_after(stream.id, 0, 10)
    assert [e.id for e in events] == [event.id]
    assert events[0].event_key == "k"
    assert events[0].id in notices.recorded_ids


async def test_an_event_for_a_deleted_stream_is_dropped_not_retried(maker, ctx):
    async with maker() as session:
        stream = await _stream(session, ctx)
        await session.execute(text("DELETE FROM streams WHERE id = :s"), {"s": stream.id})
        await session.commit()
    await EventsView(maker, _Notices()).handle(_stream_event(stream.id, ctx, "late").to_bus())


async def test_reads_page_by_position_and_by_time(maker, ctx):
    now = datetime.now(UTC)
    async with maker() as session:
        stream = await _stream(session, ctx)
        repo = StreamEventRepository(session, ctx)
        for i in range(3):
            await repo.record(
                _stream_event(stream.id, ctx, f"k{i}", received_at=now - timedelta(hours=3 - i))
            )
        await session.commit()
        oldest_first = await repo.read_after(stream.id, 0, 10)
        assert [e.event_key for e in oldest_first] == ["k0", "k1", "k2"]
        newest = await repo.read_before(stream.id, None, 2)
        assert [e.event_key for e in newest] == ["k2", "k1"]
        since = await repo.read_since(stream.id, now - timedelta(hours=2, minutes=30), 0, 10)
        assert [e.event_key for e in since] == ["k1", "k2"]
        paged = await repo.read_since(
            stream.id, now - timedelta(hours=2, minutes=30), since[0].sequence, 10
        )
        assert [e.event_key for e in paged] == ["k2"]
        assert await repo.last_received_at(stream.id) == oldest_first[-1].received_at


async def test_an_entry_event_starts_its_own_chain(maker, ctx):
    publisher, dedup = _Publisher(), _Dedup()
    async with maker() as session:
        stream = await _stream(session, ctx)
        result = await _ingest(session, ctx, publisher, dedup).append(
            stream.id, _event(), event_key="entry"
        )
    assert publisher.published[-1][1].correlation_id == str(result.event_id)
