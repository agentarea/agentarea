"""Consumer-side dedup via Redis SETNX.

Producers attach a stable dedup key as a stream field (e.g. `telegram:42:7`
for inbound, the workflow-derived `message_id` for outbound). Before doing
the side-effecting work, the consumer calls `claim(key)`. If `False`, the
message is a duplicate (broker redelivered, producer retried, etc.) and the
consumer just ACKs without re-running the side effect. The Redis key is
``<namespace>.dedup.<prefix>:<key>``.

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
        namespace: str,
        prefix: str,
        ttl_seconds: int = 86400,
    ) -> None:
        if not namespace:
            raise ValueError("DedupCache needs a namespace (AGENTAREA_EVENT_NAMESPACE)")
        self._redis_url = redis_url
        self._prefix = f"{namespace}.dedup.{prefix}"
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

    async def claim(self, key: str, *, hold_seconds: int | None = None) -> bool:
        """Return True the first time `key` is claimed, False on duplicates.

        TTL bounds the dedup window — long enough to outlast any plausible
        broker redelivery (24h default), short enough that the key set stays
        bounded. With `hold_seconds` the claim lasts only that long, for work
        in progress: ``keep`` extends it to the window once the work is done,
        and a crashed holder's claim lapses on its own.
        """
        client = await self._get_client()
        ttl = self._ttl if hold_seconds is None else hold_seconds
        ok = await client.set(f"{self._prefix}:{key}", "1", nx=True, ex=ttl)
        return bool(ok)

    async def keep(self, key: str) -> None:
        """Keep a held claim for the whole dedup window."""
        client = await self._get_client()
        await client.set(f"{self._prefix}:{key}", "1", ex=self._ttl)

    async def contains(self, key: str) -> bool:
        """Whether `key` is claimed now."""
        client = await self._get_client()
        return bool(await client.exists(f"{self._prefix}:{key}"))

    async def release(self, key: str) -> None:
        """Drop a previously-claimed key so a retry can re-claim it.

        A claim made before work that then did not happen must be released,
        or the redelivery dedup-skips the message for the whole TTL.
        """
        client = await self._get_client()
        await client.delete(f"{self._prefix}:{key}")
