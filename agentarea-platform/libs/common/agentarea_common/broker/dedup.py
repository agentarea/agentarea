"""Consumer-side dedup via Redis SETNX.

Producers attach a stable dedup key as a stream field (e.g. `telegram:42:7`
for inbound, the workflow-derived `message_id` for outbound). Before doing
the side-effecting work, the consumer calls `claim(key)`. If `False`, the
message is a duplicate (broker redelivered, producer retried, etc.) and the
consumer just ACKs without re-running the side effect.

Broker-native primitive (Redis SET with NX + EX). Swapping the broker to
Kafka would swap this for a Kafka-state-store-backed equivalent.
"""

from __future__ import annotations

import redis.asyncio as redis


class DedupCache:
    def __init__(
        self,
        redis_url: str,
        *,
        prefix: str = "dedup",
        ttl_seconds: int = 86400,
    ) -> None:
        self._redis_url = redis_url
        self._prefix = prefix
        self._ttl = ttl_seconds
        self._client: redis.Redis | None = None

    async def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def claim(self, key: str) -> bool:
        """Return True the first time `key` is claimed, False on duplicates.

        TTL bounds the dedup window — long enough to outlast any plausible
        broker redelivery (24h default), short enough that the key set stays
        bounded.
        """
        client = await self._get_client()
        ok = await client.set(f"{self._prefix}:{key}", "1", nx=True, ex=self._ttl)
        return bool(ok)

    async def release(self, key: str) -> None:
        """Drop a previously-claimed key so a retry can re-claim it.

        Used by the delivery consumer on `RetryableError`: the original
        attempt did not deliver, so the dedup slot would otherwise persist
        for the full TTL and cause the broker's redelivery (and any
        autoclaim hand-off) to dedup-skip the message — silent loss.
        """
        client = await self._get_client()
        await client.delete(f"{self._prefix}:{key}")
