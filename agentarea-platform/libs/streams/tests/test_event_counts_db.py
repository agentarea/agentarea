"""The feed's facet counts against the migrated schema.

Unfiltered, they are read from ``stream_event_counts``, which the transaction
recording each event keeps and which loses a day with its partition; under
other filters they are counted from the rows, up to a cap. Below the cap they
equal a full count of the rows. Set STREAMS_TEST_DATABASE_URL.
"""

import importlib.util
import os
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import tenant_scoped_session_class, workspace_scope
from agentarea_common.config.database import TenantScopeMode
from agentarea_common.config.streams import EventStreamSettings
from agentarea_streams.domain import StreamEvent, StreamKind
from agentarea_streams.domain.feed import FeedFilter
from agentarea_streams.domain.processing import ProcessingStatus
from agentarea_streams.infrastructure.event_repository import StreamEventRepository
from agentarea_streams.infrastructure.partitions import PartitionMaintainer
from agentarea_streams.infrastructure.repository import StreamRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")
GRANT = "agentarea_common.base.workspace_scoped_repository.grant_resource_owner"
MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "apps/api/alembic/versions/20261019_2200_stream_event_counts.py"
)

_STREAMS = ("orders", "mail", "hidden")
_SOURCES = ("generic_webhook", "mail", None, "platform")
_KINDS = ("order.paid", "order.refunded", "message", "push")


async def _partition(maker, day) -> None:
    async with maker() as session:
        await session.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS stream_events_p{day:%Y%m%d} PARTITION OF "
                f"stream_events FOR VALUES FROM ('{day} 00:00:00+00') "
                f"TO ('{day + timedelta(days=1)} 00:00:00+00')"
            )
        )
        await session.commit()


@pytest.fixture
async def world():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        sync_session_class=tenant_scoped_session_class(TenantScopeMode.ENFORCE),
        expire_on_commit=False,
    )
    raw = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    other = UserContext(user_id="u", workspace_id=str(uuid4()))
    today = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    for back in range(3):
        await _partition(raw, (today - timedelta(days=back)).date())
    streams = {}
    with patch(GRANT, new=AsyncMock()):
        for context in (ctx, other):
            with workspace_scope(context.workspace_id):
                async with maker() as session:
                    made = {
                        name: await StreamRepository(session, context).add_stream(
                            name=name, description="", kind=StreamKind.CUSTOM
                        )
                        for name in _STREAMS
                    }
                    await session.commit()
            streams[context.workspace_id] = made
    world = SimpleNamespace(
        maker=maker,
        raw=raw,
        ctx=ctx,
        other=other,
        streams=streams[ctx.workspace_id],
        other_streams=streams[other.workspace_id],
        today=today,
    )
    yield world
    async with raw() as session:
        for context in (ctx, other):
            await session.execute(
                text("DELETE FROM streams WHERE workspace_id = :ws"), {"ws": context.workspace_id}
            )
        await session.commit()
    await engine.dispose()


def _event(world, stream, *, key, received_at, source_type, kind="order.paid", ctx=None, **extra):
    ctx = ctx or world.ctx
    return StreamEvent(
        id=uuid4(),
        type=kind,
        source="test",
        data={},
        stream_id=stream.id,
        workspace_id=ctx.workspace_id,
        created_by="u",
        event_key=key,
        received_at=received_at,
        source_type=source_type,
        **extra,
    )


async def _record(world, *events, ctx=None):
    ctx = ctx or world.ctx
    with workspace_scope(ctx.workspace_id):
        async with world.maker() as session:
            repo = StreamEventRepository(session, ctx)
            recorded = [await repo.record(event) for event in events]
            await session.commit()
    return recorded


async def _counts(world, workspace_id=None):
    async with world.raw() as session:
        rows = await session.execute(
            text(
                "SELECT stream_id, day, source_type, count FROM stream_event_counts "
                "WHERE workspace_id = :ws"
            ),
            {"ws": workspace_id or world.ctx.workspace_id},
        )
        return {(r.stream_id, r.day, r.source_type): r.count for r in rows}


async def _facets(world, feed_filter, streams=None, **kwargs):
    with workspace_scope(world.ctx.workspace_id):
        async with world.maker() as session:
            return await StreamEventRepository(session, world.ctx).feed_facets(
                feed_filter,
                streams if streams is not None else [s.id for s in world.streams.values()],
                **kwargs,
            )


async def test_recording_an_event_counts_it_by_stream_day_and_source_type(world):
    orders, mail = world.streams["orders"], world.streams["mail"]
    today, yesterday = world.today, world.today - timedelta(days=1)
    first = _event(world, orders, key="a", received_at=today, source_type="generic_webhook")
    recorded = await _record(
        world,
        first,
        _event(world, orders, key="b", received_at=today, source_type="generic_webhook"),
        _event(world, orders, key="c", received_at=today, source_type=None),
        _event(world, mail, key="d", received_at=yesterday, source_type="mail"),
        first,
    )
    assert recorded == [True, True, True, True, False]

    routed = _event(world, mail, key="e", received_at=yesterday, source_type="mail")
    with workspace_scope(world.ctx.workspace_id):
        async with world.maker() as session:
            assert await StreamEventRepository(session, world.ctx).mark_routed(
                routed, 0, at=routed.received_at
            )
            await session.commit()

    assert await _counts(world) == {
        (orders.id, today.date(), "generic_webhook"): 2,
        (orders.id, today.date(), ""): 1,
        (mail.id, yesterday.date(), "mail"): 2,
    }


async def test_the_count_is_written_with_its_event_or_not_at_all(world):
    orders = world.streams["orders"]
    with workspace_scope(world.ctx.workspace_id):
        async with world.maker() as session:
            repo = StreamEventRepository(session, world.ctx)
            await repo.record(
                _event(world, orders, key="a", received_at=world.today, source_type="mail")
            )
            await session.rollback()
    assert await _counts(world) == {}


async def test_a_deleted_stream_takes_its_counts(world):
    await _record(
        world,
        _event(world, world.streams["hidden"], key="a", received_at=world.today, source_type=None),
    )
    async with world.raw() as session:
        await session.execute(
            text("DELETE FROM streams WHERE id = :id"), {"id": world.streams["hidden"].id}
        )
        await session.commit()
    assert await _counts(world) == {}


def _migration():
    spec = importlib.util.spec_from_file_location("_stream_event_counts", MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_the_backfill_counts_every_recorded_event():
    """On temporary tables of the same names, so the migrated tables are untouched."""
    module = _migration()
    a, b = uuid4(), uuid4()
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "CREATE TEMP TABLE stream_events (workspace_id text, created_by text, "
                    "stream_id uuid, source_type text, received_at timestamptz)"
                )
            )
            await conn.execute(
                text(
                    "CREATE TEMP TABLE stream_event_counts (workspace_id text, created_by text, "
                    "stream_id uuid, day date, source_type text, count bigint, "
                    "PRIMARY KEY (workspace_id, stream_id, day, source_type))"
                )
            )
            utc, moscow = UTC, timezone(timedelta(hours=3))
            rows = [
                ("w", a, "mail", datetime(2026, 10, 18, 23, 59, 59, tzinfo=utc)),
                ("w", a, "mail", datetime(2026, 10, 18, tzinfo=utc)),
                # 01:30 in Moscow is still the 18th in UTC, the day of its partition.
                ("w", a, "mail", datetime(2026, 10, 19, 1, 30, tzinfo=moscow)),
                ("w", a, None, datetime(2026, 10, 18, 10, tzinfo=utc)),
                ("w", a, "mail", datetime(2026, 10, 19, tzinfo=utc)),
                ("w", b, "repo", datetime(2026, 10, 19, 8, tzinfo=utc)),
                ("v", b, "repo", datetime(2026, 10, 19, 8, tzinfo=utc)),
            ]
            for ws, stream, source_type, at in rows:
                await conn.execute(
                    text("INSERT INTO stream_events VALUES (:w, 'u', :s, :t, :at)"),
                    {"w": ws, "s": stream, "t": source_type, "at": at},
                )
            await conn.execute(text("SET LOCAL TIME ZONE 'Asia/Tokyo'"))
            await conn.execute(text(module.BACKFILL))
            counted = (
                await conn.execute(
                    text(
                        "SELECT workspace_id, stream_id, day::text, source_type, count "
                        "FROM stream_event_counts"
                    )
                )
            ).all()
            await conn.rollback()
    finally:
        await engine.dispose()

    assert {tuple(row[:4]): row[4] for row in counted} == {
        ("w", a, "2026-10-18", "mail"): 3,
        ("w", a, "2026-10-18", ""): 1,
        ("w", a, "2026-10-19", "mail"): 1,
        ("w", b, "2026-10-19", "repo"): 1,
        ("v", b, "2026-10-19", "repo"): 1,
    }


async def test_a_dropped_day_takes_its_counts(world):
    old_day = (world.today - timedelta(days=40)).date()
    await _partition(world.raw, old_day)
    orders = world.streams["orders"]
    old = world.today - timedelta(days=40)
    await _record(
        world,
        _event(world, orders, key="old", received_at=old, source_type="mail"),
        _event(world, orders, key="new", received_at=world.today, source_type="mail"),
    )
    assert await _counts(world) == {
        (orders.id, old_day, "mail"): 1,
        (orders.id, world.today.date(), "mail"): 1,
    }

    report = await PartitionMaintainer(
        world.raw, EventStreamSettings(PARTITIONS_AHEAD=2, RETENTION=timedelta(days=30))
    ).run_once()

    assert f"stream_events_p{old_day:%Y%m%d}" in report.dropped
    assert await _counts(world) == {(orders.id, world.today.date(), "mail"): 1}
    facets = await _facets(world, FeedFilter())
    assert facets.streams == {orders.id: 1}


async def _seed(world):
    """A spread of events over three days, three streams and four source types."""
    events = []
    for i in range(90):
        stream = world.streams[_STREAMS[i % 3]]
        events.append(
            _event(
                world,
                stream,
                key=f"k{i}",
                received_at=world.today - timedelta(days=i % 3, minutes=i),
                source_type=_SOURCES[(i // 3) % 4],
                kind=_KINDS[(i // 2) % 4],
                sender=("alice", "bob", None)[i % 3],
                session_key=("s:1", None)[i % 2],
            )
        )
    await _record(world, *events)
    await _record(
        world,
        *(
            _event(
                world,
                world.other_streams["orders"],
                key=f"o{i}",
                received_at=world.today,
                source_type="mail",
                ctx=world.other,
            )
            for i in range(5)
        ),
        ctx=world.other,
    )
    async with world.raw() as session:
        await session.execute(
            text(
                "UPDATE stream_events SET routed_at = received_at, subscribers = 0 "
                "WHERE workspace_id = :ws AND event_key LIKE 'k%' "
                "AND right(event_key, 1) IN ('0', '3', '6')"
            ),
            {"ws": world.ctx.workspace_id},
        )
        await session.commit()


_FACET = {
    "stream": ("stream_id", "s.stream_id = :stream_id"),
    "source_type": ("source_type", "s.source_type = :source_type"),
}


async def _exact(world, feed_filter: FeedFilter, streams):
    """The full count the rollup replaces: a GROUP BY over every row, each facet ignoring itself."""
    f = feed_filter
    others = []
    if f.kind is not None:
        others.append("s.kind LIKE :kind_prefix" if f.kind.endswith(".*") else "s.kind = :kind")
    if f.sender is not None:
        others.append("s.sender = :sender")
    if f.session_key is not None:
        others.append("s.session_key = :session_key")
    if f.result is ProcessingStatus.QUEUED:
        others.append("s.routed_at IS NULL")
    if f.result is ProcessingStatus.NO_HANDLERS:
        others.append("s.routed_at IS NOT NULL AND s.subscribers = 0 AND s.reacted = 0")
    if f.since is not None:
        others.append("s.received_at >= :since")
    if f.until is not None:
        others.append("s.received_at < :until")
    params = {
        "ws": world.ctx.workspace_id,
        "streams": list(streams),
        "stream_id": f.stream_id,
        "source_type": f.source_type,
        "kind": f.kind,
        "kind_prefix": (f.kind or "")[:-1] + "%",
        "sender": f.sender,
        "session_key": f.session_key,
        "since": f.since,
        "until": f.until,
    }
    result = {}
    for facet, (column, own) in _FACET.items():
        where = ["s.workspace_id = :ws", "s.stream_id = ANY(:streams)", *others]
        if facet == "source_type":
            where.append("s.source_type IS NOT NULL")
        for other, (_, condition) in _FACET.items():
            value = f.stream_id if other == "stream" else f.source_type
            if other != facet and value is not None:
                where.append(condition)
        async with world.raw() as session:
            rows = await session.execute(
                text(
                    f"SELECT s.{column}, count(*) FROM stream_events s "
                    f"WHERE {' AND '.join(where)} GROUP BY s.{column}"
                ),
                params,
            )
            result[facet] = dict(rows.tuples().all())
    return result


def _filters(world):
    mail = world.streams["mail"].id
    return [
        FeedFilter(),
        FeedFilter(platform=False),
        FeedFilter(stream_id=mail),
        FeedFilter(source_type="mail"),
        FeedFilter(stream_id=mail, source_type="generic_webhook"),
        FeedFilter(kind="order.*"),
        FeedFilter(kind="message", stream_id=mail),
        FeedFilter(sender="alice", source_type="platform"),
        FeedFilter(session_key="s:1"),
        FeedFilter(result=ProcessingStatus.QUEUED),
        FeedFilter(result=ProcessingStatus.NO_HANDLERS, kind="push"),
        FeedFilter(since=world.today - timedelta(days=1, minutes=30)),
        FeedFilter(until=world.today - timedelta(hours=2), sender="bob"),
    ]


async def test_facets_equal_a_full_count_of_the_rows(world):
    await _seed(world)
    for readable in (_STREAMS, ("orders", "mail")):
        streams = [world.streams[name].id for name in readable]
        for feed_filter in _filters(world):
            facets = await _facets(world, feed_filter, streams, cap=10_000)
            exact = await _exact(world, feed_filter, streams)
            assert not facets.capped, feed_filter
            assert facets.streams == exact["stream"], feed_filter
            assert facets.source_types == exact["source_type"], feed_filter


async def test_unfiltered_facets_are_not_capped(world):
    await _seed(world)
    facets = await _facets(world, FeedFilter(stream_id=world.streams["mail"].id), cap=5)
    assert not facets.capped
    assert facets.streams == {s.id: 30 for s in world.streams.values()}


async def test_counts_under_other_filters_stop_at_the_cap(world):
    await _seed(world)
    feed_filter = FeedFilter(kind="order.*")
    exact = await _exact(world, feed_filter, [s.id for s in world.streams.values()])
    assert sum(exact["stream"].values()) == 46

    exactly = await _facets(world, feed_filter, cap=46)
    assert not exactly.capped
    assert exactly.streams == exact["stream"]

    capped = await _facets(world, feed_filter, cap=13)
    assert capped.capped
    assert sum(capped.streams.values()) == 14
    for stream, count in capped.streams.items():
        assert count <= exact["stream"][stream]
    for source, count in capped.source_types.items():
        assert count <= exact["source_type"][source]
