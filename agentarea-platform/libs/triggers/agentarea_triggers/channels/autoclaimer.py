"""Background loop that runs XAUTOCLAIM to recover entries from dead
consumers. Pairs with `ChannelDeliveryConsumer`: when a worker crashes
mid-process, its PEL entries stay unowned until something claims them.

A single autoclaimer per stream/group is enough — it can be co-resident
with the consumer.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentarea_common.broker import BrokerClient

logger = logging.getLogger(__name__)


class StreamAutoclaimer:
    def __init__(
        self,
        broker: BrokerClient,
        *,
        stream: str,
        group: str,
        consumer_id: str,
        min_idle_ms: int = 60_000,
        interval_seconds: float = 30.0,
    ) -> None:
        self._broker = broker
        self._stream = stream
        self._group = group
        self._consumer_id = consumer_id
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

    async def _run_loop(self) -> None:
        while self._running:
            try:
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
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("autoclaim error on %s", self._stream)
            await asyncio.sleep(self._interval)
