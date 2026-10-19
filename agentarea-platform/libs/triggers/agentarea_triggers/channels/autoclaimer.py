"""Background loop that runs XAUTOCLAIM and settles what it reclaims.

A consumer reads only new entries, so an entry it left un-ACKed -- a
retryable failure, a channel this worker has no adapter for during a rolling
deploy, a worker that crashed mid-process -- is picked up only here. Once it
has been pending for `min_idle_ms` the entry is claimed and handed to the
consumer's `handle`, which delivers and ACKs it or leaves it pending again for
the next pass; the consumer's delivery-count cap dead-letters one that never
settles.

A single autoclaimer per stream/group is enough — it can be co-resident
with the consumer.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from agentarea_common.broker import BrokerClient, BrokerMessage
from agentarea_common.events.adapters.redis_streams import STOPPED_CONSUMER_IDLE_MS

logger = logging.getLogger(__name__)


class StreamAutoclaimer:
    def __init__(
        self,
        broker: BrokerClient,
        *,
        stream: str,
        group: str,
        consumer_id: str,
        handle: Callable[[BrokerMessage], Awaitable[None]],
        min_idle_ms: int = 60_000,
        interval_seconds: float = 30.0,
    ) -> None:
        self._broker = broker
        self._stream = stream
        self._group = group
        self._consumer_id = consumer_id
        self._handle = handle
        self._min_idle_ms = min_idle_ms
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name=f"autoclaim:{self._stream}")
        logger.info(
            "StreamAutoclaimer started (stream=%s group=%s min_idle=%dms)",
            self._stream,
            self._group,
            self._min_idle_ms,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("StreamAutoclaimer stopped (stream=%s)", self._stream)

    async def reclaim(self) -> int:
        """Claim the entries idle past `min_idle_ms` and handle each; returns how many."""
        reclaimed = await self._broker.autoclaim(
            self._stream,
            self._group,
            self._consumer_id,
            min_idle_ms=self._min_idle_ms,
        )
        if reclaimed:
            logger.info(
                "autoclaimed %d entries on %s (now owned by %s)",
                len(reclaimed),
                self._stream,
                self._consumer_id,
            )
        for msg in reclaimed:
            await self._handle(msg)
        # Each process joins under its own name; the names of stopped ones go once
        # they hold nothing.
        await self._broker.prune_consumers(
            self._stream, self._group, idle_ms=STOPPED_CONSUMER_IDLE_MS
        )
        return len(reclaimed)

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self.reclaim()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("autoclaim error on %s", self._stream)
            await asyncio.sleep(self._interval)
