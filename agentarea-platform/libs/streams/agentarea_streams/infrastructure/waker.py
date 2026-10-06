"""Redis pub/sub wake-up for stream dispatchers. Latency only: the poll is what is correct."""

import asyncio
import logging
from collections.abc import Callable
from uuid import UUID

import redis.asyncio as redis
from redis.exceptions import RedisError

from ..domain.ports import StreamWaker

logger = logging.getLogger(__name__)

WAKE_CHANNEL = "agentarea.streams.wake"


class RedisStreamWaker(StreamWaker):
    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._client: redis.Redis | None = None

    def _redis(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    async def wake(self, stream_id: UUID) -> None:
        try:
            await self._redis().publish(WAKE_CHANNEL, str(stream_id))
        except RedisError:
            # The event is already committed; the dispatcher's poll picks it up.
            logger.warning(
                "Wake for stream %s not published; the dispatcher's poll picks it up",
                stream_id,
                exc_info=True,
            )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class RedisWakeListener:
    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._task: asyncio.Task[None] | None = None

    async def start(self, on_wake: Callable[[UUID], None]) -> None:
        self._task = asyncio.create_task(self._listen(on_wake), name="stream-wake-listener")

    async def _listen(self, on_wake: Callable[[UUID], None]) -> None:
        while True:
            client = redis.from_url(self._redis_url, decode_responses=True)
            pubsub = client.pubsub()
            try:
                await pubsub.subscribe(WAKE_CHANNEL)
                async for message in pubsub.listen():
                    if message.get("type") == "message":
                        on_wake(UUID(message["data"]))
            except asyncio.CancelledError:
                raise
            except (RedisError, ValueError):
                logger.warning(
                    "Stream wake listener lost Redis; resubscribing in 1s", exc_info=True
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
