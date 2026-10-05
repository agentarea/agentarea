"""Partitions are kept ahead, expired days dropped, short-retention streams trimmed.

Set STREAMS_TEST_DATABASE_URL.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agentarea_common.config.streams import EventStreamSettings
from agentarea_streams.infrastructure.partitions import PartitionMaintainer, PartitionReport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")


async def _exists(session, name: str) -> bool:
    return (await session.execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": name})).scalar_one()


async def test_partitions_are_created_ahead_and_old_ones_dropped():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    today = datetime.now(UTC).date()
    settings = EventStreamSettings(PARTITIONS_AHEAD=20, RETENTION=timedelta(days=30))

    # check-db.sh runs every schema-backed suite as one pytest invocation against
    # one shared, never-reset database; earlier streams suites commit real
    # `streams` rows, and run_once() computes its drop horizon from
    # max(MAX(streams.retention_days), settings.RETENTION.days). Reading that
    # same aggregate here (with a margin) keeps this test honest about what the
    # maintainer actually does, instead of assuming no committed row ever
    # exceeds this test's own RETENTION override.
    async with maker() as session:
        existing_max = (
            await session.execute(text("SELECT max(retention_days) FROM streams"))
        ).scalar_one() or 0
    keep_days = max(existing_max, settings.RETENTION.days) + 5
    old_day = today - timedelta(days=keep_days)

    async with maker() as session:
        await session.execute(text(
            f"CREATE TABLE IF NOT EXISTS stream_events_p{old_day:%Y%m%d} PARTITION OF stream_events "
            f"FOR VALUES FROM ('{old_day} 00:00:00+00') TO ('{old_day + timedelta(days=1)} 00:00:00+00')"
        ))
        await session.commit()

    report = await PartitionMaintainer(maker, settings).run_once()

    async with maker() as session:
        assert await _exists(session, f"stream_events_p{(today + timedelta(days=20)):%Y%m%d}")
        assert not await _exists(session, f"stream_events_p{old_day:%Y%m%d}")
    assert f"stream_events_p{old_day:%Y%m%d}" in report.dropped
    await engine.dispose()


async def test_two_concurrent_runs_both_succeed_one_may_skip():
    """Overlapping run_once() calls (e.g. two worker replicas) never both act:

    the advisory lock lets only one in; the loser's DDL would be idempotent
    even without it, but the lock keeps the horizon/drop decision from running
    twice. Either interleaving must leave both calls completed without error.
    """
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    settings = EventStreamSettings()
    maintainer = PartitionMaintainer(maker, settings)

    reports = await asyncio.gather(maintainer.run_once(), maintainer.run_once())

    assert len(reports) == 2
    assert all(isinstance(r, PartitionReport) for r in reports)
    today = datetime.now(UTC).date()
    ahead = today + timedelta(days=settings.PARTITIONS_AHEAD)
    async with maker() as session:
        assert await _exists(session, f"stream_events_p{ahead:%Y%m%d}")
    await engine.dispose()


async def test_a_short_retention_stream_is_trimmed_inside_kept_partitions():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ws, stream_id = str(uuid4()), uuid4()
    eight_days_ago = datetime.now(UTC) - timedelta(days=8)
    async with maker() as session:
        await session.execute(text(
            "INSERT INTO streams (id, workspace_id, created_by, name, description, kind, "
            "retention_days, created_at, updated_at) VALUES (:id, :ws, 'u', 'short', '', 'custom', 7, now(), now())"
        ), {"id": stream_id, "ws": ws})
        day = eight_days_ago.date()
        await session.execute(text(
            f"CREATE TABLE IF NOT EXISTS stream_events_p{day:%Y%m%d} PARTITION OF stream_events "
            f"FOR VALUES FROM ('{day} 00:00:00+00') TO ('{day + timedelta(days=1)} 00:00:00+00')"
        ))
        await session.execute(text(
            "INSERT INTO stream_event_keys (stream_id, event_key, sequence, received_at) "
            "VALUES (:s, 'k', nextval('stream_events_sequence_seq'), :at)"
        ), {"s": stream_id, "at": eight_days_ago})
        await session.execute(text(
            "INSERT INTO stream_events (sequence, received_at, stream_id, event_id, event_key, kind, "
            "source, occurred_at, data, workspace_id, created_by) SELECT sequence, received_at, "
            "stream_id, gen_random_uuid(), event_key, 'k', 's', received_at, '{}', :ws, 'u' "
            "FROM stream_event_keys WHERE stream_id = :s"
        ), {"s": stream_id, "ws": ws})
        await session.commit()

    report = await PartitionMaintainer(maker, EventStreamSettings()).run_once()

    async with maker() as session:
        left = await session.execute(text("SELECT count(*) FROM stream_events WHERE stream_id = :s"), {"s": stream_id})
        keys = await session.execute(text("SELECT count(*) FROM stream_event_keys WHERE stream_id = :s"), {"s": stream_id})
        assert left.scalar_one() == 0
        assert keys.scalar_one() == 0
    assert report.trimmed_events >= 1
    await engine.dispose()
