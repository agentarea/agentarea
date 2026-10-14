"""Batches analytics events to the collector; a failed batch is logged and dropped.

An unreachable collector is logged once with its traceback, then at most once a day
with the count of events dropped since, and once more when sending recovers.
"""

import asyncio
import logging
from collections import Counter, deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from agentarea_common import __version__
from agentarea_common.config import get_app_settings
from agentarea_common.outbound import Destination, outbound_client

from .constants import COLLECTOR_KEY, COLLECTOR_URL

logger = logging.getLogger(__name__)

MAX_BATCH = 500
#: Distinct (name, labels) counters held between roll-ups; past it a counter is
#: folded into its name under ``{"overflow": "true"}``.
MAX_COUNTER_SERIES = 1000
_OVERFLOW = (("overflow", "true"),)
_FAILURE_LOG_EVERY = timedelta(days=1)


def _collector_client() -> httpx.AsyncClient:
    return outbound_client(Destination.VENDOR, timeout=5.0)


class AnalyticsSender:
    """Holds events in memory and posts them to the collector on a fixed interval.

    Analytics never fails a request or a job: nothing here raises to a caller. Off,
    it queues nothing and sends nothing.
    """

    def __init__(
        self,
        *,
        enabled: bool,
        install_id: str | None,
        client_factory: Callable[[], httpx.AsyncClient] = _collector_client,
        flush_every: timedelta = timedelta(hours=1),
        max_queued: int = 10_000,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if enabled and not install_id:
            raise ValueError("an enabled AnalyticsSender needs the install_id it reports as")
        self._enabled = enabled
        self._context = {
            "install_id": install_id,
            "version": __version__,
            "edition": get_app_settings().EDITION,
        }
        self._client_factory = client_factory
        self._flush_every = flush_every
        self._queue: deque[dict[str, Any]] = deque(maxlen=max_queued)
        self._counts: Counter[tuple[str, tuple[tuple[str, str], ...]]] = Counter()
        self._task: asyncio.Task[None] | None = None
        self._clock = clock
        # Since the first failure after a success: when it was last logged, and the
        # events dropped since then and in all.
        self._failure_logged_at: datetime | None = None
        self._dropped_unlogged = 0
        self._dropped_in_outage = 0

    def enqueue(self, event: dict[str, Any]) -> None:
        """Queue ``event`` (``event``, ``properties``, optionally ``occurred_at``)."""
        if not self._enabled:
            return
        self._queue.append(
            {
                "occurred_at": datetime.now(UTC).isoformat(),
                "properties": {},
                **event,
                "context": self._context,
            }
        )

    def count(self, name: str, labels: dict[str, str]) -> None:
        """Add one to the failure counter ``name`` under ``labels``; sent with the next roll-up."""
        if not self._enabled:
            return
        key = (name, tuple(sorted(labels.items())))
        if key not in self._counts and len(self._counts) >= MAX_COUNTER_SERIES:
            key = (name, _OVERFLOW)
        self._counts[key] += 1

    def roll_up_counters(self) -> None:
        """Queue the counts since the last roll-up as one ``counters`` event, and reset them."""
        counts, self._counts = self._counts, Counter()
        if counts:
            self.enqueue(
                {
                    "event": "counters",
                    "properties": {
                        "counters": [
                            {"name": name, "labels": dict(labels), "count": n}
                            for (name, labels), n in counts.items()
                        ]
                    },
                }
            )

    async def flush(self) -> int:
        """Send everything queued; returns how many events the collector accepted."""
        events = list(self._queue)
        self._queue.clear()
        if not events:
            return 0
        sent = 0
        async with self._client_factory() as client:
            for start in range(0, len(events), MAX_BATCH):
                batch = events[start : start + MAX_BATCH]
                try:
                    response = await client.post(
                        f"{COLLECTOR_URL}/v1/events",
                        json=batch,
                        headers={"Authorization": f"Bearer {COLLECTOR_KEY}"},
                    )
                    response.raise_for_status()
                except Exception as error:
                    self._dropped(len(batch), error)
                    continue
                self._recovered()
                sent += len(batch)
        return sent

    def _dropped(self, n: int, error: Exception) -> None:
        now = self._clock()
        self._dropped_in_outage += n
        if self._failure_logged_at is None:
            logger.warning(
                "Dropped %d analytics events the collector did not accept", n, exc_info=error
            )
            self._failure_logged_at = now
            return
        self._dropped_unlogged += n
        if now - self._failure_logged_at >= _FAILURE_LOG_EVERY:
            logger.warning(
                "The analytics collector is still not accepting events; dropped %d since %s",
                self._dropped_unlogged,
                self._failure_logged_at.isoformat(),
            )
            self._failure_logged_at = now
            self._dropped_unlogged = 0

    def _recovered(self) -> None:
        if self._failure_logged_at is None:
            return
        logger.info(
            "The analytics collector accepts events again; %d were dropped meanwhile",
            self._dropped_in_outage,
        )
        self._failure_logged_at = None
        self._dropped_unlogged = 0
        self._dropped_in_outage = 0

    async def start(self) -> None:
        if self._enabled and self._task is None:
            self._task = asyncio.create_task(self._run_loop(), name="analytics-sender")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._send_all()

    async def _run_loop(self) -> None:
        while True:
            await asyncio.sleep(self._flush_every.total_seconds())
            await self._send_all()

    async def _send_all(self) -> None:
        try:
            self.roll_up_counters()
            await self.flush()
        except Exception:
            logger.warning("Analytics flush failed", exc_info=True)
