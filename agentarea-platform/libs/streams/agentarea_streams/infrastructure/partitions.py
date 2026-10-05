"""Keep daily journal partitions ahead of today and drop or trim expired days.

Runs inside the worker. Infrastructure across every workspace, so it declares
why it is unscoped. ``CREATE TABLE ... PARTITION OF`` has no SQLAlchemy
construct and is the one statement written as text.
"""

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import cast

from agentarea_common.base.tenant_scope import unscoped
from agentarea_common.config.streams import EventStreamSettings
from sqlalchemy import (
    Integer,
    MetaData,
    Table,
    column,
    delete,
    func,
    literal_column,
    select,
    table,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.schema import DropTable

from .orm import StreamEventKeyORM, StreamEventORM, StreamORM

logger = logging.getLogger(__name__)

_PARTITION = re.compile(r"^stream_events_p(\d{8})$")

#: Fixed, arbitrary key for pg_try_advisory_xact_lock: one maintenance pass at
#: a time across every worker replica. Transaction-scoped, so it releases
#: itself on commit or rollback -- no unlock call needed.
_ADVISORY_LOCK_KEY = 798_021_335_641


def _utcnow() -> datetime:
    return datetime.now(UTC)


def partition_name(day: date) -> str:
    return f"stream_events_p{day:%Y%m%d}"


@dataclass
class PartitionReport:
    created: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    trimmed_events: int = 0


class PartitionMaintainer:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: EventStreamSettings,
        clock: Callable[[], datetime] = _utcnow,
    ):
        self._session_factory = session_factory
        self._settings = settings
        self._clock = clock
        self._task: asyncio.Task[None] | None = None

    async def run_once(self) -> PartitionReport:
        report = PartitionReport()
        today = self._clock().date()
        with unscoped("journal partitions span every workspace"):
            async with self._session_factory() as session:
                acquired = (
                    await session.execute(
                        select(func.pg_try_advisory_xact_lock(_ADVISORY_LOCK_KEY))
                    )
                ).scalar_one()
                if not acquired:
                    logger.info(
                        "Journal partition maintenance already running in another process; "
                        + "skipping this pass"
                    )
                    return report
                for offset in range(-1, self._settings.PARTITIONS_AHEAD + 1):
                    day = today + timedelta(days=offset)
                    if await self._create(session, day):
                        report.created.append(partition_name(day))
                longest = await session.execute(select(func.max(StreamORM.retention_days)))
                keep_days = max(longest.scalar_one() or 0, self._settings.RETENTION.days)
                horizon = today - timedelta(days=keep_days)
                for name, day in await self._partitions(session):
                    if day < horizon:
                        await session.execute(DropTable(Table(name, MetaData()), if_exists=True))
                        report.dropped.append(name)
                await session.execute(
                    delete(StreamEventKeyORM).where(
                        StreamEventKeyORM.received_at
                        < datetime.combine(horizon, datetime.min.time(), tzinfo=UTC)
                    )
                )
                report.trimmed_events = await self._trim_short_streams(session)
                await session.commit()
        if report.created or report.dropped or report.trimmed_events:
            logger.info(
                "Journal partitions: created %s, dropped %s, trimmed %d events",
                report.created,
                report.dropped,
                report.trimmed_events,
            )
        return report

    async def _create(self, session: AsyncSession, day: date) -> bool:
        name = partition_name(day)
        exists = await session.execute(select(func.to_regclass(name).is_not(None)))
        if exists.scalar_one():
            return False
        following = day + timedelta(days=1)
        await session.execute(
            text(
                f'CREATE TABLE IF NOT EXISTS "{name}" PARTITION OF stream_events FOR VALUES FROM '
                + f"('{day.isoformat()} 00:00:00+00') TO ('{following.isoformat()} 00:00:00+00')"
            )
        )
        return True

    async def _partitions(self, session: AsyncSession) -> list[tuple[str, date]]:
        inherits = table("pg_inherits", column("inhrelid"), column("inhparent"))
        child = table("pg_class", column("oid"), column("relname")).alias("c")
        parent = table("pg_class", column("oid"), column("relname")).alias("p")
        result = await session.execute(
            select(child.c.relname)
            .select_from(
                inherits.join(child, child.c.oid == inherits.c.inhrelid).join(
                    parent, parent.c.oid == inherits.c.inhparent
                )
            )
            .where(parent.c.relname == "stream_events")
        )
        found: list[tuple[str, date]] = []
        for (name,) in result.all():
            match = _PARTITION.match(name)
            if match is None:
                raise RuntimeError(f"Unexpected stream_events partition {name!r}")
            found.append((name, datetime.strptime(match.group(1), "%Y%m%d").date()))
        return found

    async def _trim_short_streams(self, session: AsyncSession) -> int:
        # Core on the tables: the ORM-enabled form of this DELETE returns no rows.
        events, keys, streams = (
            cast(Table, model.__table__) for model in (StreamEventORM, StreamEventKeyORM, StreamORM)
        )
        expired = (
            delete(events)
            .where(
                events.c.stream_id == streams.c.id,
                events.c.received_at
                < func.now() - func.make_interval(0, 0, 0, streams.c.retention_days),
            )
            .returning(events.c.stream_id, events.c.event_key)
            .cte("expired")
        )
        trimmed = await session.execute(
            delete(keys)
            .where(keys.c.stream_id == expired.c.stream_id, keys.c.event_key == expired.c.event_key)
            .returning(literal_column("1", Integer))
        )
        return len(trimmed.all())

    async def start(self, interval: timedelta = timedelta(hours=1)) -> None:
        try:
            await self.run_once()
        except Exception:
            # The worker must not start without partitions ahead of today; log with
            # the traceback before re-raising so the failure is diagnosable even if
            # the caller's own startup logging does not carry this context.
            logger.exception("Journal partition maintenance failed on startup")
            raise
        self._task = asyncio.create_task(self._loop(interval), name="stream-partitions")

    async def _loop(self, interval: timedelta) -> None:
        while True:
            await asyncio.sleep(interval.total_seconds())
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Journal partition maintenance failed; retrying next interval")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
