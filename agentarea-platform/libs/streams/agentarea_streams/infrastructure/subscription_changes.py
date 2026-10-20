"""The router's configuration cache follows subscription changes on ``domain.events``.

``StreamService`` enqueues a ``streams.subscriptions.changed`` domain event in
the same transaction as the change; the outbox relay publishes it to
``domain.events.streams.subscriptions.changed``. Every worker reads that topic
without a group, from the newest entry when it starts, and drops its whole
cache first: what changed before it was listening is read fresh anyway. After a
failed read it drops the whole cache again and resumes from where it was.
"""

import asyncio
import logging
from collections.abc import Callable
from uuid import UUID

from agentarea_common.broker import BrokerClient
from agentarea_common.broker.topics import domain_events_topic
from agentarea_common.events.adapters.redis_streams import decode

from ..domain.events import SUBSCRIPTIONS_CHANGED

logger = logging.getLogger(__name__)

TOPIC = domain_events_topic(SUBSCRIPTIONS_CHANGED)


def changed_stream(data: dict) -> UUID | None:
    """The stream a change notice names; ``None`` (drop every stream) when it names none."""
    stream_id = data.get("stream_id")
    return UUID(str(stream_id)) if stream_id else None


class SubscriptionChangeListener:
    def __init__(self, broker: BrokerClient, *, retry_seconds: float = 1.0, block_ms: int = 5000):
        self._broker = broker
        self._retry_seconds = retry_seconds
        self._block_ms = block_ms
        self._task: asyncio.Task[None] | None = None

    async def start(self, on_change: Callable[[UUID | None], None]) -> None:
        cursor = await self._broker.last_id(TOPIC)
        on_change(None)
        self._task = asyncio.create_task(
            self._listen(cursor, on_change), name="stream-subscription-changes"
        )

    async def _listen(self, cursor: str, on_change: Callable[[UUID | None], None]) -> None:
        while True:
            try:
                cursor, messages = await self._broker.tail(
                    TOPIC, last_id=cursor, block_ms=self._block_ms
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Reading subscription changes failed; dropping every cached stream and "
                    + "retrying in %.0fs",
                    self._retry_seconds,
                    exc_info=True,
                )
                on_change(None)
                await asyncio.sleep(self._retry_seconds)
                continue
            for message in messages:
                try:
                    on_change(changed_stream(decode(message.fields).data))
                except ValueError, TypeError, KeyError:
                    logger.warning(
                        "Unreadable subscription change notice %s; dropping every cached stream",
                        message.id,
                        exc_info=True,
                    )
                    on_change(None)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
