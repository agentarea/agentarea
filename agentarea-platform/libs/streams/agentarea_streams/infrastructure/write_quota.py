"""The workspace write quota, counted where events enter, over a sliding minute.

The events read model is written by a consumer group after the fact, so a count
of it lags a burst and lets the quota be overshot. The counter is taken in Redis
as each event is admitted: this minute's count plus the previous minute's,
weighted by how much of it the sliding window still covers.
"""

from datetime import datetime

import redis.asyncio as redis

_WINDOW_SECONDS = 60


class WriteQuota:
    def __init__(self, redis_url: str, *, namespace: str) -> None:
        if not namespace:
            raise ValueError("WriteQuota needs a namespace (AGENTAREA_EVENT_NAMESPACE)")
        self._redis_url = redis_url
        self._prefix = f"{namespace}.quota.stream-writes"
        self._client: redis.Redis | None = None

    async def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def take(self, workspace_id: str, limit: int, now: datetime) -> bool:
        """Count one event for the workspace; False, uncounted, when it would pass ``limit``."""
        client = await self._get_client()
        minute = int(now.timestamp()) // _WINDOW_SECONDS
        key = f"{self._prefix}:{workspace_id}:{minute}"
        async with client.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, 2 * _WINDOW_SECONDS)
            pipe.get(f"{self._prefix}:{workspace_id}:{minute - 1}")
            current, _, previous = await pipe.execute()
        covered = 1 - (now.timestamp() % _WINDOW_SECONDS) / _WINDOW_SECONDS
        if int(current) + int(previous or 0) * covered > limit:
            await client.decr(key)
            return False
        return True
