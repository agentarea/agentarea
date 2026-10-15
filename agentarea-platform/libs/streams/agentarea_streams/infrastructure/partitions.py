"""Keep daily partitions of the events read model ahead of today; drop expired days.

Runs inside the worker. Infrastructure across every workspace, so it declares
why it is unscoped. ``CREATE TABLE ... PARTITION OF`` has no SQLAlchemy
construct and is the one statement written as text.

A day older than ``AGENTAREA_EVENT_RETENTION`` is dropped whole. Every step
commits on its own: partition DDL takes an ACCESS EXCLUSIVE lock on
``stream_events``, blocking the events view's writes and every read. DDL waits
at most ``lock_timeout`` for that lock and is retried by the next pass.
"""

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from agentarea_common.base.tenant_scope import unscoped
from agentarea_common.config.streams import EventStreamSettings
from sqlalchemy import Executable, MetaData, Table, column, func, select, table, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.schema import DropTable

logger = logging.getLogger(__name__)

_PARTITION = re.compile(r"^stream_events_p(\d{8})$")

#: Fixed, arbitrary key for pg_try_advisory_xact_lock: one maintenance pass at
#: a time across every worker replica. Held by a transaction kept open for the
#: whole pass while each step commits on a session of its own; it releases
#: itself when that transaction ends, so a crashed worker cannot leave it behind.
_ADVISORY_LOCK_KEY = 798_021_335_641

_LOCK_NOT_AVAILABLE = "55P03"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def partition_name(day: date) -> str:
    return f"stream_events_p{day:%Y%m%d}"


@dataclass
class PartitionReport:
    created: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)


class PartitionMaintainer:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: EventStreamSettings,
        clock: Callable[[], datetime] = _utcnow,
        *,
        lock_timeout: timedelta = timedelta(seconds=5),
    ):
        self._session_factory = session_factory
        self._settings = settings
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
                    if day < horizon and await self._ddl(
                        name, DropTable(Table(name, MetaData()), if_exists=True), report
                    ):
                        report.dropped.append(name)
        if report.created or report.dropped or report.deferred:
            logger.info(
                "Event partitions: created %s, dropped %s, deferred %s",
                report.created,
                report.dropped,
                report.deferred,
            )
        return report

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
        if await self._ddl(name, statement, report):
            report.created.append(name)

    async def _ddl(self, name: str, statement: Executable, report: PartitionReport) -> bool:
        """Run one DDL statement in its own short transaction; False when the lock wait ran out."""
        timeout = f"{int(self._lock_timeout.total_seconds() * 1000)}ms"
        async with self._session_factory() as session:
            await session.execute(select(func.set_config("lock_timeout", timeout, True)))
            try:
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
