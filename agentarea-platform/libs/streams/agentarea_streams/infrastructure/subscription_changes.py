"""The router's configuration cache follows subscription changes from the domain path.

``StreamService`` enqueues a ``streams.subscriptions.changed`` domain event in
the same transaction as the change; the outbox relay publishes it. A listener
that lost Redis may have missed some, so on every (re)subscribe it drops the
whole cache.
"""

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

import redis.asyncio as redis
from agentarea_common.events.shared_event_format import get_channel_for_event_type
from redis.exceptions import RedisError

from ..domain.events import SUBSCRIPTIONS_CHANGED

logger = logging.getLogger(__name__)

CHANNEL = get_channel_for_event_type(SUBSCRIPTIONS_CHANGED)


def changed_stream(payload: str) -> UUID | None:
    """The stream a change notice names; ``None`` (drop every stream) when it names none."""
    message: dict[str, Any] = json.loads(payload)
    data: dict[str, Any] = message.get("data") or {}
    stream_id = data.get("stream_id")
    return UUID(str(stream_id)) if stream_id else None


class SubscriptionChangeListener:
    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._task: asyncio.Task[None] | None = None

    async def start(self, on_change: Callable[[UUID | None], None]) -> None:
        self._task = asyncio.create_task(
            self._listen(on_change), name="stream-subscription-changes"
        )

    async def _listen(self, on_change: Callable[[UUID | None], None]) -> None:
        while True:
            client = redis.from_url(self._redis_url, decode_responses=True)
            pubsub = client.pubsub()
            try:
                await pubsub.subscribe(CHANNEL)
                on_change(None)
                async for message in pubsub.listen():
                    notice: dict[str, Any] = message
                    if notice.get("type") != "message":
                        continue
                    try:
                        on_change(changed_stream(str(notice["data"])))
                    except (ValueError, TypeError):
                        logger.warning(
                            "Unreadable subscription change notice; dropping every cached stream",
                            exc_info=True,
                        )
                        on_change(None)
            except asyncio.CancelledError:
                raise
            except RedisError:
                logger.warning(
                    "Subscription change listener lost Redis; resubscribing in 1s", exc_info=True
                )
                await asyncio.sleep(1)
            finally:
                await pubsub.aclose()
                await client.aclose()

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
