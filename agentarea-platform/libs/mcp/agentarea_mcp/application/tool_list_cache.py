"""Short-lived cache for a member MCP's tool list.

The upstream server is the source of truth: its tool list is a live answer
about its own runtime, not a fact this system owns, so it is not kept as one.
Persisting it would make us a stale mirror with no invalidation signal — a
third-party remote changes its tools without anything on our side moving, and
an instance we launched ourselves can be rebuilt underneath us just the same.

So the serving path calls upstream honestly and this sits in front of it purely
to keep the cost off the hot path: a short TTL, and an explicit drop when a tool
call fails, which is the one signal an upstream actually gives us that our view
of it is wrong.

Redis rather than process memory: the API runs several replicas behind an
ingress with no session affinity, and a per-process cache would have them
answering differently for the same client.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

import redis.asyncio as redis

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 60


class ToolListCache(Protocol):
    """What the aggregator needs from a cache; keeps Redis out of its tests."""

    async def get(self, instance_id: str) -> list[dict[str, Any]] | None: ...

    async def set(self, instance_id: str, tools: list[dict[str, Any]]) -> None: ...

    async def invalidate(self, instance_id: str) -> None: ...


class RedisToolListCache:
    """Redis-backed ``ToolListCache``.

    Every operation is best-effort: a cache outage must slow the bundle down,
    not break it, so failures fall through to the live path and are logged.
    """

    def __init__(
        self,
        redis_url: str,
        *,
        prefix: str = "mcp:tools",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
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

    def _key(self, instance_id: str) -> str:
        return f"{self._prefix}:{instance_id}"

    async def get(self, instance_id: str) -> list[dict[str, Any]] | None:
        try:
            client = await self._get_client()
            raw = await client.get(self._key(instance_id))
        except Exception:
            logger.warning("Tool-list cache read failed for %s", instance_id, exc_info=True)
            return None
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except ValueError:
            logger.warning("Discarding unreadable cached tool list for %s", instance_id)
            return None
        return value if isinstance(value, list) else None

    async def set(self, instance_id: str, tools: list[dict[str, Any]]) -> None:
        try:
            client = await self._get_client()
            await client.set(self._key(instance_id), json.dumps(tools), ex=self._ttl)
        except Exception:
            logger.warning("Tool-list cache write failed for %s", instance_id, exc_info=True)

    async def invalidate(self, instance_id: str) -> None:
        try:
            client = await self._get_client()
            await client.delete(self._key(instance_id))
        except Exception:
            logger.warning("Tool-list cache invalidation failed for %s", instance_id, exc_info=True)
