"""Keep daily journal partitions ahead of today and drop or trim expired days.

Runs inside the worker. Infrastructure across every workspace, so its SQL is
Core on purpose and declares why it is unscoped.
"""

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from agentarea_common.base.tenant_scope import unscoped
from agentarea_common.config.streams import EventStreamSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

_PARTITION = re.compile(r"^stream_events_p(\d{8})$")


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
                for offset in range(-1, self._settings.PARTITIONS_AHEAD + 1):
                    day = today + timedelta(days=offset)
                    if await self._create(session, day):
                        report.created.append(partition_name(day))
                longest = await session.execute(text("SELECT max(retention_days) FROM streams"))
                keep_days = max(longest.scalar_one() or 0, self._settings.RETENTION.days)
                horizon = today - timedelta(days=keep_days)
                for name, day in await self._partitions(session):
                    if day < horizon:
                        await session.execute(text(f'DROP TABLE "{name}"'))
                        report.dropped.append(name)
                await session.execute(
                    text("DELETE FROM stream_event_keys WHERE received_at < :h"),
                    {"h": datetime.combine(horizon, datetime.min.time(), tzinfo=UTC)},
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
        exists = await session.execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": name})
        if exists.scalar_one():
            return False
        following = day + timedelta(days=1)
        await session.execute(
            text(
                f'CREATE TABLE "{name}" PARTITION OF stream_events FOR VALUES FROM '
                f"('{day.isoformat()} 00:00:00+00') TO ('{following.isoformat()} 00:00:00+00')"
            )
        )
        return True

    async def _partitions(self, session: AsyncSession) -> list[tuple[str, date]]:
        result = await session.execute(
            text(
                "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'stream_events'"
            )
        )
        found: list[tuple[str, date]] = []
        for (name,) in result.all():
            match = _PARTITION.match(name)
            if match is None:
                raise RuntimeError(f"Unexpected stream_events partition {name!r}")
            found.append((name, datetime.strptime(match.group(1), "%Y%m%d").date()))
        return found

    async def _trim_short_streams(self, session: AsyncSession) -> int:
        trimmed = await session.execute(
            text(
                "WITH expired AS ("
                " DELETE FROM stream_events e USING streams s"
                " WHERE e.stream_id = s.id"
                "   AND e.received_at < now() - make_interval(days => s.retention_days)"
                " RETURNING e.stream_id, e.event_key) "
                "DELETE FROM stream_event_keys k USING expired x"
                " WHERE k.stream_id = x.stream_id AND k.event_key = x.event_key"
                " RETURNING 1"
            )
        )
        return len(trimmed.all())

    async def start(self, interval: timedelta = timedelta(hours=1)) -> None:
        await self.run_once()
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
