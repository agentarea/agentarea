"""Partitions are kept ahead, expired days dropped, short-retention streams trimmed.

Set STREAMS_TEST_DATABASE_URL.
"""

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.events.ports import IntegrationEvent
from agentarea_streams.infrastructure.journal_repository import StreamJournal
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


async def _one_partition_to_create(maker) -> tuple[int, str]:
    """PARTITIONS_AHEAD that makes a pass create exactly one partition, and its name."""
    today = datetime.now(UTC).date()
    async with maker() as session:
        names = (
            await session.execute(
                text(
                    "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                    "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'stream_events'"
                )
            )
        ).scalars().all()
    last = max(datetime.strptime(n.removeprefix("stream_events_p"), "%Y%m%d").date() for n in names)
    ahead = (last - today).days + 1
    return ahead, f"stream_events_p{today + timedelta(days=ahead):%Y%m%d}"


async def _drop(maker, name: str) -> None:
    async with maker() as session:
        await session.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
        await session.commit()


async def _committed_stream(maker, retention_days: int = 30) -> tuple[UserContext, UUID]:
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    stream_id = uuid4()
    async with maker() as session:
        await session.execute(
            text(
                "INSERT INTO streams (id, workspace_id, created_by, name, description, kind, "
                "retention_days, created_at, updated_at) "
                "VALUES (:id, :ws, 'u', :n, '', 'custom', :r, now(), now())"
            ),
            {"id": stream_id, "ws": ctx.workspace_id, "n": f"s-{stream_id}", "r": retention_days},
        )
        await session.commit()
    return ctx, stream_id


async def test_intake_appends_while_the_pass_that_created_a_partition_is_still_trimming(
    monkeypatch,
):
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ahead, created = await _one_partition_to_create(maker)
    ctx, stream_id = await _committed_stream(maker)
    maintainer = PartitionMaintainer(maker, EventStreamSettings(PARTITIONS_AHEAD=ahead))
    trimming, release = asyncio.Event(), asyncio.Event()
    trim = maintainer._trim_short_streams

    async def held_open(*args, **kwargs):
        trimming.set()
        await release.wait()
        return await trim(*args, **kwargs)

    monkeypatch.setattr(maintainer, "_trim_short_streams", held_open)
    run = asyncio.create_task(maintainer.run_once())
    try:
        await asyncio.wait_for(trimming.wait(), 10)
        async with maker() as session:
            journal = StreamJournal(session, ctx, EventStreamSettings())
            appended = await asyncio.wait_for(
                journal.append(
                    stream_id,
                    IntegrationEvent(type="push", source="webhook:test", data={}),
                    event_key="during-trim",
                ),
                3,
            )
            await session.commit()
        assert appended.appended
    finally:
        release.set()
        report = await run
        await _drop(maker, created)
    assert report.created == [created]
    await engine.dispose()


async def test_a_partition_created_before_a_failing_trim_stays_created(monkeypatch):
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ahead, created = await _one_partition_to_create(maker)
    maintainer = PartitionMaintainer(maker, EventStreamSettings(PARTITIONS_AHEAD=ahead))
    monkeypatch.setattr(
        maintainer, "_trim_short_streams", AsyncMock(side_effect=RuntimeError("trim failed"))
    )
    try:
        with pytest.raises(RuntimeError, match="trim failed"):
            await maintainer.run_once()
        async with maker() as session:
            assert await _exists(session, created)
    finally:
        await _drop(maker, created)
    await engine.dispose()


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


async def test_expired_keys_and_short_stream_rows_go_in_bounded_batches(monkeypatch):
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    settings = EventStreamSettings()
    ctx, short = await _committed_stream(maker, retention_days=1)
    _, long_lived = await _committed_stream(maker)
    async with maker() as session:
        longest = (
            await session.execute(text("SELECT max(retention_days) FROM streams"))
        ).scalar_one()
    past_horizon = datetime.now(UTC) - timedelta(days=max(longest, settings.RETENTION.days) + 2)
    three_days_ago = datetime.now(UTC) - timedelta(days=3)
    day = three_days_ago.date()
    async with maker() as session:
        await session.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS stream_events_p{day:%Y%m%d} PARTITION OF "
                f"stream_events FOR VALUES FROM ('{day} 00:00:00+00') "
                f"TO ('{day + timedelta(days=1)} 00:00:00+00')"
            )
        )
        for n in range(3):
            await session.execute(
                text(
                    "INSERT INTO stream_event_keys (stream_id, event_key, sequence, received_at) "
                    "VALUES (:s, :k, nextval('stream_events_sequence_seq'), :at)"
                ),
                {"s": long_lived, "k": f"old-{n}", "at": past_horizon},
            )
        for n in range(5):
            await session.execute(
                text(
                    "INSERT INTO stream_event_keys (stream_id, event_key, sequence, received_at) "
                    "VALUES (:s, :k, nextval('stream_events_sequence_seq'), :at)"
                ),
                {"s": short, "k": f"short-{n}", "at": three_days_ago},
            )
        await session.execute(
            text(
                "INSERT INTO stream_events (sequence, received_at, stream_id, event_id, event_key, "
                "kind, source, occurred_at, data, workspace_id, created_by) SELECT sequence, "
                "received_at, stream_id, gen_random_uuid(), event_key, 'k', 's', received_at, "
                "'{}', :ws, 'u' FROM stream_event_keys WHERE stream_id = :s"
            ),
            {"s": short, "ws": ctx.workspace_id},
        )
        await session.commit()

    maintainer = PartitionMaintainer(maker, settings, batch_size=2)
    batches: list[str] = []
    for step in ("_prune_key_batch", "_trim_batch"):
        original = getattr(maintainer, step)

        async def counted(*args, _original=original, _step=step, **kwargs):
            batches.append(_step)
            return await _original(*args, **kwargs)

        monkeypatch.setattr(maintainer, step, counted)

    report = await maintainer.run_once()

    async with maker() as session:
        for stream_id in (short, long_lived):
            keys = await session.execute(
                text("SELECT count(*) FROM stream_event_keys WHERE stream_id = :s"),
                {"s": stream_id},
            )
            assert keys.scalar_one() == 0
        events = await session.execute(
            text("SELECT count(*) FROM stream_events WHERE stream_id = :s"), {"s": short}
        )
        assert events.scalar_one() == 0
    assert report.trimmed_events >= 5
    assert batches.count("_prune_key_batch") >= 2
    assert batches.count("_trim_batch") >= 3
    await engine.dispose()
