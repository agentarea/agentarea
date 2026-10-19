"""Partitions of the events read model are kept ahead and days past retention dropped.

Set STREAMS_TEST_DATABASE_URL.
"""

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta

import pytest
from agentarea_common.config.streams import EventStreamSettings
from agentarea_streams.infrastructure.partitions import PartitionMaintainer, PartitionReport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")


async def _exists(session, name: str) -> bool:
    return (
        await session.execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": name})
    ).scalar_one()


async def _partition(maker, day) -> str:
    name = f"stream_events_p{day:%Y%m%d}"
    async with maker() as session:
        await session.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF stream_events "
                f"FOR VALUES FROM ('{day} 00:00:00+00') TO ('{day + timedelta(days=1)} 00:00:00+00')"
            )
        )
        await session.commit()
    return name


async def test_partitions_are_created_ahead_and_days_past_retention_dropped():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    today = datetime.now(UTC).date()
    settings = EventStreamSettings(PARTITIONS_AHEAD=20, RETENTION=timedelta(days=30))
    old = await _partition(maker, today - timedelta(days=35))
    kept = await _partition(maker, today - timedelta(days=29))

    report = await PartitionMaintainer(maker, settings).run_once()

    async with maker() as session:
        assert await _exists(session, f"stream_events_p{(today + timedelta(days=20)):%Y%m%d}")
        assert not await _exists(session, old)
        assert await _exists(session, kept)
    assert old in report.dropped
    await engine.dispose()


async def test_the_default_retention_keeps_a_week():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    today = datetime.now(UTC).date()
    eight_days_old = await _partition(maker, today - timedelta(days=8))
    six_days_old = await _partition(maker, today - timedelta(days=6))

    report = await PartitionMaintainer(maker, EventStreamSettings()).run_once()

    async with maker() as session:
        assert not await _exists(session, eight_days_old)
        assert await _exists(session, six_days_old)
    assert eight_days_old in report.dropped
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


async def _one_partition_to_create(maker) -> tuple[int, str]:
    """PARTITIONS_AHEAD that makes a pass create exactly one partition, and its name."""
    today = datetime.now(UTC).date()
    async with maker() as session:
        names = (
            (
                await session.execute(
                    text(
                        "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                        "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'stream_events'"
                    )
                )
            )
            .scalars()
            .all()
        )
    last = max(datetime.strptime(n.removeprefix("stream_events_p"), "%Y%m%d").date() for n in names)
    ahead = (last - today).days + 1
    return ahead, f"stream_events_p{today + timedelta(days=ahead):%Y%m%d}"


async def _drop(maker, name: str) -> None:
    async with maker() as session:
        await session.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
        await session.commit()


async def test_a_partition_the_parent_lock_keeps_out_waits_for_the_next_pass(caplog):
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ahead, created = await _one_partition_to_create(maker)
    maintainer = PartitionMaintainer(
        maker,
        EventStreamSettings(PARTITIONS_AHEAD=ahead),
        lock_timeout=timedelta(milliseconds=200),
    )
    try:
        async with engine.connect() as reader:
            await reader.execute(text("LOCK TABLE stream_events IN ACCESS SHARE MODE"))
            with caplog.at_level(logging.WARNING, logger="agentarea_streams"):
                deferred = await maintainer.run_once()
            await reader.rollback()
        assert deferred.created == []
        assert deferred.deferred == [created]
        assert any("lock_timeout" in r.getMessage() for r in caplog.records)
        async with maker() as session:
            assert not await _exists(session, created)

        assert (await maintainer.run_once()).created == [created]
    finally:
        await _drop(maker, created)
    await engine.dispose()
