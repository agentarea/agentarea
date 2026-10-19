"""Keep daily partitions of the events read model ahead of today; drop expired days.

Runs inside the worker. Infrastructure across every workspace, so it declares
why it is unscoped. ``CREATE TABLE ... PARTITION OF`` has no SQLAlchemy
construct and is the one statement written as text.

A day older than ``AGENTAREA_EVENT_RETENTION`` is dropped whole, its rows of
``stream_event_counts`` in the same transaction. With
``AGENTAREA_EVENT_ARCHIVE`` on, its events are first written to the object
store, one gzipped JSONL object per workspace; a day the store does not take is
kept, and the next pass tries again. Every step commits on its own: partition DDL takes an ACCESS EXCLUSIVE lock on
``stream_events``, blocking the events view's writes and every read. DDL waits
at most ``lock_timeout`` for that lock and is retried by the next pass.
"""

import asyncio
import gzip
import logging
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import quote

from agentarea_common.base.tenant_scope import unscoped
from agentarea_common.config.streams import EventStreamSettings
from sqlalchemy import Executable, MetaData, Table, column, delete, func, select, table, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.schema import DropTable

from ..domain.feed import RoutedEvent
from .event_archive import EventArchive
from .event_repository import to_routed
from .orm import StreamEventCountORM, StreamEventORM

logger = logging.getLogger(__name__)

_PARTITION = re.compile(r"^stream_events_p(\d{8})$")

#: Fixed, arbitrary key for pg_try_advisory_xact_lock: one maintenance pass at
#: a time across every worker replica. Held by a transaction kept open for the
#: whole pass while each step commits on a session of its own; it releases
#: itself when that transaction ends, so a crashed worker cannot leave it behind.
_ADVISORY_LOCK_KEY = 798_021_335_641

_LOCK_NOT_AVAILABLE = "55P03"

#: An archive object is kept in memory up to this size, then spills to a temporary file.
_SPOOL_IN_MEMORY = 8 * 1024 * 1024
_ARCHIVE_BATCH = 500


def _utcnow() -> datetime:
    return datetime.now(UTC)


def partition_name(day: date) -> str:
    return f"stream_events_p{day:%Y%m%d}"


def archive_key(workspace_id: str, day: date) -> str:
    return f"event-archive/{quote(workspace_id, safe='')}/{day:%Y-%m-%d}.jsonl.gz"


@dataclass
class PartitionReport:
    created: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    #: Object keys written to the archive.
    archived: list[str] = field(default_factory=list)
    #: Expired days not dropped because archiving them failed.
    kept: list[str] = field(default_factory=list)


class _Spool:
    """One workspace's events of a day, gzipped JSONL, until it is stored."""

    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id
        self._file = tempfile.SpooledTemporaryFile(max_size=_SPOOL_IN_MEMORY)
        self._gzip = gzip.GzipFile(fileobj=self._file, mode="wb")

    def write(self, event: RoutedEvent) -> None:
        self._gzip.write(event.model_dump_json().encode("utf-8") + b"\n")

    async def store(self, archive: EventArchive, day: date) -> str:
        key = archive_key(self.workspace_id, day)
        self._gzip.close()
        self._file.seek(0)
        await archive.put(key, self._file)
        return key

    def close(self) -> None:
        self._gzip.close()
        self._file.close()


class PartitionMaintainer:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: EventStreamSettings,
        clock: Callable[[], datetime] = _utcnow,
        *,
        archive: EventArchive | None = None,
        lock_timeout: timedelta = timedelta(seconds=5),
    ):
        if settings.ARCHIVE and archive is None:
            raise ValueError("AGENTAREA_EVENT_ARCHIVE is on, but no event archive was given")
        self._session_factory = session_factory
        self._settings = settings
        self._archive = archive
        self._clock = clock
        self._lock_timeout = lock_timeout
        self._task: asyncio.Task[None] | None = None

    async def run_once(self) -> PartitionReport:
        report = PartitionReport()
        now = self._clock()
        today = now.date()
        with unscoped("read-model partitions span every workspace"):
            async with self._session_factory() as pass_lock:
                acquired = (
                    await pass_lock.execute(
                        select(func.pg_try_advisory_xact_lock(_ADVISORY_LOCK_KEY))
                    )
                ).scalar_one()
                if not acquired:
                    logger.info(
                        "Event partition maintenance already running in another process; "
                        + "skipping this pass"
                    )
                    return report
                for offset in range(-1, self._settings.PARTITIONS_AHEAD + 1):
                    if report.deferred:
                        break
                    await self._create(today + timedelta(days=offset), report)
                horizon = today - timedelta(days=self._settings.RETENTION.days)
                for name, day in await self._partitions():
                    if report.deferred:
                        break
                    if day >= horizon or not await self._archived(name, day, report):
                        continue
                    if await self._ddl(
                        name,
                        report,
                        DropTable(Table(name, MetaData()), if_exists=True),
                        delete(StreamEventCountORM).where(StreamEventCountORM.day == day),
                    ):
                        report.dropped.append(name)
        if report.created or report.dropped or report.deferred or report.kept:
            logger.info(
                "Event partitions: created %s, dropped %s, deferred %s, kept %s",
                report.created,
                report.dropped,
                report.deferred,
                report.kept,
            )
        return report

    async def _archived(self, name: str, day: date, report: PartitionReport) -> bool:
        """True when the day may be dropped: archived, or archiving is off."""
        archive = self._archive if self._settings.ARCHIVE else None
        if archive is None:
            return True
        try:
            keys = await self._write_archive(archive, day)
        except Exception:
            logger.error(
                "Event partition %s kept: archiving it to the object store failed; "
                + "the next pass tries again",
                name,
                exc_info=True,
            )
            report.kept.append(name)
            return False
        report.archived.extend(keys)
        return True

    async def _write_archive(self, archive: EventArchive, day: date) -> list[str]:
        start = datetime.combine(day, time.min, UTC)
        keys: list[str] = []
        spool: _Spool | None = None
        try:
            async with self._session_factory() as session:
                rows = await session.stream_scalars(
                    select(StreamEventORM)
                    .where(
                        StreamEventORM.received_at >= start,
                        StreamEventORM.received_at < start + timedelta(days=1),
                    )
                    .order_by(StreamEventORM.workspace_id, StreamEventORM.sequence)
                    .execution_options(yield_per=_ARCHIVE_BATCH)
                )
                async for row in rows:
                    if spool is None or spool.workspace_id != row.workspace_id:
                        if spool is not None:
                            keys.append(await spool.store(archive, day))
                            spool.close()
                        spool = _Spool(row.workspace_id)
                    spool.write(to_routed(row))
            if spool is not None:
                keys.append(await spool.store(archive, day))
        finally:
            if spool is not None:
                spool.close()
        return keys

    async def _create(self, day: date, report: PartitionReport) -> None:
        name = partition_name(day)
        async with self._session_factory() as session:
            exists = await session.execute(select(func.to_regclass(name).is_not(None)))
            if exists.scalar_one():
                return
        following = day + timedelta(days=1)
        statement = text(
            f'CREATE TABLE IF NOT EXISTS "{name}" PARTITION OF stream_events FOR VALUES FROM '
            + f"('{day.isoformat()} 00:00:00+00') TO ('{following.isoformat()} 00:00:00+00')"
        )
        if await self._ddl(name, report, statement):
            report.created.append(name)

    async def _ddl(self, name: str, report: PartitionReport, *statements: Executable) -> bool:
        """Run DDL in its own short transaction; False when the lock wait ran out."""
        timeout = f"{int(self._lock_timeout.total_seconds() * 1000)}ms"
        async with self._session_factory() as session:
            await session.execute(select(func.set_config("lock_timeout", timeout, True)))
            try:
                for statement in statements:
                    await session.execute(statement)
                await session.commit()
            except DBAPIError as error:
                if getattr(error.orig, "sqlstate", None) != _LOCK_NOT_AVAILABLE:
                    raise
                await session.rollback()
                # Readers and writers held stream_events past lock_timeout. Waiting
                # longer would queue every append behind this DDL; the next pass
                # tries again, and partitions are kept days ahead of need.
                logger.warning(
                    "Event partition %s deferred to the next pass: lock_timeout %s ran out "
                    + "waiting for stream_events",
                    name,
                    timeout,
                    exc_info=True,
                )
                report.deferred.append(name)
                return False
        return True

    async def _partitions(self) -> list[tuple[str, date]]:
        inherits = table("pg_inherits", column("inhrelid"), column("inhparent"))
        child = table("pg_class", column("oid"), column("relname")).alias("c")
        parent = table("pg_class", column("oid"), column("relname")).alias("p")
        async with self._session_factory() as session:
            result = await session.execute(
                select(child.c.relname)
                .select_from(
                    inherits.join(child, child.c.oid == inherits.c.inhrelid).join(
                        parent, parent.c.oid == inherits.c.inhparent
                    )
                )
                .where(parent.c.relname == "stream_events")
            )
            names = [name for (name,) in result.all()]
        found: list[tuple[str, date]] = []
        for name in names:
            match = _PARTITION.match(name)
            if match is None:
                raise RuntimeError(f"Unexpected stream_events partition {name!r}")
            found.append((name, datetime.strptime(match.group(1), "%Y%m%d").date()))
        return found

    async def start(self, interval: timedelta = timedelta(hours=1)) -> None:
        try:
            await self.run_once()
        except Exception:
            # The worker must not start without partitions ahead of today; log with
            # the traceback before re-raising so the failure is diagnosable even if
            # the caller's own startup logging does not carry this context.
            logger.exception("Event partition maintenance failed on startup")
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
                logger.exception("Event partition maintenance failed; retrying next interval")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
