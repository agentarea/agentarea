"""A day past retention is archived to the object store before it is dropped.

With ``AGENTAREA_EVENT_ARCHIVE`` on, each workspace's events of the day go to
one gzipped JSONL object; a day that cannot be archived is kept for the next
pass. Set STREAMS_TEST_DATABASE_URL.
"""

import gzip
import json
import logging
import os
from datetime import UTC, datetime, time, timedelta
from typing import BinaryIO
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import tenant_scoped_session_class, workspace_scope
from agentarea_common.config.database import TenantScopeMode
from agentarea_common.config.streams import EventStreamSettings
from agentarea_streams.domain import StreamEvent, StreamKind
from agentarea_streams.domain.keys import event_id_for
from agentarea_streams.infrastructure.event_repository import StreamEventRepository
from agentarea_streams.infrastructure.partitions import PartitionMaintainer, partition_name
from agentarea_streams.infrastructure.repository import StreamRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")
GRANT = "agentarea_common.base.workspace_scoped_repository.grant_resource_owner"
ARCHIVING = EventStreamSettings(ARCHIVE=True, RETENTION=timedelta(days=30))


class _Archive:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, body: BinaryIO) -> None:
        if self.fail:
            raise ConnectionError("object store unreachable")
        self.objects[key] = body.read()

    def lines(self, key: str) -> list[dict]:
        return [json.loads(line) for line in gzip.decompress(self.objects[key]).splitlines()]


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


async def _day_with_events(maker, day, workspaces: dict[str, int]) -> dict[str, list[UUID]]:
    """A partition for ``day`` holding the given number of events per workspace."""
    name = partition_name(day)
    async with maker() as session:
        await session.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF stream_events "
                f"FOR VALUES FROM ('{day} 00:00:00+00') TO ('{day + timedelta(days=1)} 00:00:00+00')"
            )
        )
        await session.commit()
    written: dict[str, list[UUID]] = {}
    for workspace_id, count in workspaces.items():
        ctx = UserContext(user_id="u", workspace_id=workspace_id)
        with workspace_scope(workspace_id):
            async with maker() as session:
                with patch(GRANT, new=AsyncMock()):
                    stream = await StreamRepository(session, ctx).add_stream(
                        name=f"s-{uuid4()}", description="", kind=StreamKind.CUSTOM
                    )
                for n in range(count):
                    event = StreamEvent(
                        id=event_id_for(stream.id, f"k{n}"),
                        type="order.paid",
                        source="test",
                        data={"n": n},
                        stream_id=stream.id,
                        workspace_id=workspace_id,
                        created_by=ctx.user_id,
                        event_key=f"k{n}",
                        received_at=datetime.combine(day, time(12, n), UTC),
                    )
                    await StreamEventRepository(session, ctx).record(event)
                    written.setdefault(workspace_id, []).append(event.id)
                await session.commit()
    return written


async def _exists(maker, name: str) -> bool:
    async with maker() as session:
        return (
            await session.execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": name})
        ).scalar_one()


async def test_each_workspace_s_events_of_an_expired_day_are_archived_then_the_day_dropped(maker):
    day = datetime.now(UTC).date() - timedelta(days=41)
    first, second = str(uuid4()), str(uuid4())
    written = await _day_with_events(maker, day, {first: 3, second: 1})
    archive = _Archive()

    report = await PartitionMaintainer(maker, ARCHIVING, archive=archive).run_once()

    key = f"event-archive/{first}/{day:%Y-%m-%d}.jsonl.gz"
    other = f"event-archive/{second}/{day:%Y-%m-%d}.jsonl.gz"
    assert {key, other} <= set(archive.objects)
    rows = archive.lines(key)
    assert [UUID(row["id"]) for row in rows] == written[first]
    assert {row["workspace_id"] for row in rows} == {first}
    assert rows[0]["type"] == "order.paid"
    assert rows[0]["data"] == {"n": 0}
    assert "sequence" in rows[0]
    assert "routed_at" in rows[0]
    assert [UUID(row["id"]) for row in archive.lines(other)] == written[second]
    assert {key, other} <= set(report.archived)
    assert partition_name(day) in report.dropped
    assert not await _exists(maker, partition_name(day))


async def test_a_day_the_store_does_not_take_is_kept(maker, caplog):
    day = datetime.now(UTC).date() - timedelta(days=42)
    await _day_with_events(maker, day, {str(uuid4()): 1})
    maintainer = PartitionMaintainer(maker, ARCHIVING, archive=_Archive(fail=True))

    with caplog.at_level(logging.ERROR, logger="agentarea_streams"):
        report = await maintainer.run_once()

    assert partition_name(day) in report.kept
    assert partition_name(day) not in report.dropped
    assert await _exists(maker, partition_name(day))
    failure = next(r for r in caplog.records if partition_name(day) in r.getMessage())
    assert failure.exc_info is not None

    retried = await PartitionMaintainer(maker, ARCHIVING, archive=_Archive()).run_once()
    assert partition_name(day) in retried.dropped


async def test_an_empty_expired_day_is_dropped_with_nothing_archived(maker):
    day = datetime.now(UTC).date() - timedelta(days=43)
    await _day_with_events(maker, day, {})
    archive = _Archive()

    report = await PartitionMaintainer(maker, ARCHIVING, archive=archive).run_once()

    assert partition_name(day) in report.dropped
    assert not [k for k in archive.objects if k.endswith(f"/{day:%Y-%m-%d}.jsonl.gz")]


def test_archiving_on_needs_a_store():
    with pytest.raises(ValueError, match="AGENTAREA_EVENT_ARCHIVE"):
        PartitionMaintainer(MagicMock(), ARCHIVING)
