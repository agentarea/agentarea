"""Redis-backed short-lived cache for upstream MCP tool lists."""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

import redis.asyncio as redis

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 60


class ToolListCache(Protocol):
    """What the aggregator needs from a cache; keys include runtime identity."""

    async def get(self, cache_key: str) -> list[dict[str, Any]] | None: ...

    async def set(
        self,
        cache_key: str,
        tools: list[dict[str, Any]],
        *,
        ttl_ms: int | None = None,
    ) -> None: ...

    async def invalidate(self, cache_key: str) -> None: ...


class RedisToolListCache:
    """Redis-backed ``ToolListCache`` with per-response expiry."""

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

    def _key(self, cache_key: str) -> str:
        return f"{self._prefix}:{cache_key}"

    async def get(self, cache_key: str) -> list[dict[str, Any]] | None:
        try:
            client = await self._get_client()
            raw = await client.get(self._key(cache_key))
        except Exception:
            logger.warning("Tool-list cache read failed for %s", cache_key, exc_info=True)
            return None
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except ValueError:
            logger.warning("Discarding unreadable cached tool list for %s", cache_key)
            return None
        return value if isinstance(value, list) else None

    async def set(
        self,
        cache_key: str,
        tools: list[dict[str, Any]],
        *,
        ttl_ms: int | None = None,
    ) -> None:
        try:
            client = await self._get_client()
            if ttl_ms is None:
                await client.set(self._key(cache_key), json.dumps(tools), ex=self._ttl)
            elif ttl_ms > 0:
                await client.set(self._key(cache_key), json.dumps(tools), px=int(ttl_ms))
            else:
                await client.delete(self._key(cache_key))
        except Exception:
            logger.warning("Tool-list cache write failed for %s", cache_key, exc_info=True)

    async def invalidate(self, cache_key: str) -> None:
        try:
            client = await self._get_client()
            await client.delete(self._key(cache_key))
        except Exception:
            logger.warning("Tool-list cache invalidation failed for %s", cache_key, exc_info=True)
