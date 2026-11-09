"""Whether a client's runner is connected: a key its socket keeps alive in Redis.

The socket sets the key on ``hello`` and on every ``ping``; it lapses
``PRESENCE_SECONDS`` after the last one, so a runner that went away shows
offline within that time, whichever API process held its socket.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

import redis.asyncio as redis

# Three missed pings.
PRESENCE_SECONDS = 30


class RunnerPresence:
    def __init__(self, redis_url: str, *, prefix: str = "runners:online") -> None:
        self._redis_url = redis_url
        self._prefix = prefix
        self._client: redis.Redis | None = None

    async def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    def _key(self, client_id: UUID) -> str:
        return f"{self._prefix}:{client_id}"

    async def mark(self, client_id: UUID) -> None:
        client = await self._get_client()
        await client.set(self._key(client_id), "1", ex=PRESENCE_SECONDS)

    async def online(self, client_ids: Iterable[UUID]) -> set[UUID]:
        ids = list(dict.fromkeys(client_ids))
        if not ids:
            return set()
        client = await self._get_client()
        values = await client.mget([self._key(client_id) for client_id in ids])
        return {client_id for client_id, value in zip(ids, values, strict=True) if value}


_presence: RunnerPresence | None = None


def runner_presence() -> RunnerPresence:
    """The process's presence client, on the broker's Redis."""
    global _presence
    if _presence is None:
        from agentarea_common.config import RedisSettings, get_settings

        settings = get_settings()
        if not isinstance(settings.broker, RedisSettings):
            raise RuntimeError(
                "runner presence lives in Redis; set AGENTAREA_BROKER=redis "
                + f"(current: {settings.broker.BROKER})"
            )
        _presence = RunnerPresence(settings.broker.REDIS_URL)
    return _presence
