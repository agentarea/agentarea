"""Shared MCP client transport, era negotiation, and Redis verdict caching."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, Protocol

import httpx2
import redis.asyncio as redis
from agentarea_common.utils.url_safety import (
    OutboundPolicy,
    PinnedSender,
    Resolver,
    SafeOutboundTransport,
    UnsafeUrlError,
    resolve_host,
)
from mcp import Client, MCPError
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp_types import DiscoverResult

from agentarea_mcp.verification import mcp_transport_candidates

logger = logging.getLogger(__name__)

MODERN_PROTOCOL_VERSION = "2026-07-28"
LEGACY_VERDICT = "legacy"
ERA_VERDICT_TTL_SECONDS = 24 * 60 * 60
NEGOTIATION_ERROR_CODES = frozenset({-32022, -32601})
# v1 parity: the SDK's streamable HTTP client used a 300 s read timeout for SSE
# responses, and a tool call may legitimately stream that long.
SSE_READ_TIMEOUT_SECONDS = 300.0
MCP_CONNECT_TIMEOUT_SECONDS = 30.0


class EraVerdictStore(Protocol):
    """Durable store for a server's negotiated MCP protocol era."""

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str) -> None: ...

    async def delete(self, key: str) -> None: ...


class RedisEraVerdictStore:
    """Redis-backed protocol-era verdicts with a 24-hour expiry."""

    def __init__(
        self,
        redis_url: str,
        *,
        prefix: str = "mcp:era",
        ttl_seconds: int = ERA_VERDICT_TTL_SECONDS,
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

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    async def get(self, key: str) -> str | None:
        try:
            return await (await self._get_client()).get(self._key(key))
        except Exception:
            logger.warning("MCP era verdict read failed for %s", key, exc_info=True)
            return None

    async def set(self, key: str, value: str) -> None:
        try:
            await (await self._get_client()).set(self._key(key), value, ex=self._ttl)
        except Exception:
            logger.warning("MCP era verdict write failed for %s", key, exc_info=True)

    async def delete(self, key: str) -> None:
        try:
            await (await self._get_client()).delete(self._key(key))
        except Exception:
            logger.warning("MCP era verdict invalidation failed for %s", key, exc_info=True)


def runtime_identity_fingerprint(fields: Mapping[str, Any] | Any) -> str:
    """Hash the canonical JSON identity of the runtime selected for an instance."""
    canonical = json.dumps(
        fields,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def mcp_verdict_key(instance_id: str | Any, fields: Mapping[str, Any] | Any) -> str:
    """Build the Redis key component for an instance and its runtime identity."""
    return f"{instance_id}:{runtime_identity_fingerprint(fields)}"


_shared_store: RedisEraVerdictStore | None = None


def shared_era_verdict_store() -> RedisEraVerdictStore | None:
    """The process-wide verdict store, or ``None`` when no Redis is configured.

    One instance per process: the store owns a connection pool, and the
    services that use it are constructed per request.
    """
    global _shared_store
    if _shared_store is None:
        from agentarea_common.config import get_settings

        settings = get_settings()
        redis_url = getattr(settings.broker, "REDIS_URL", None) or settings.mcp.REDIS_URL
        if not redis_url:
            return None
        _shared_store = RedisEraVerdictStore(redis_url)
    return _shared_store


class UnsafeMCPDestinationError(httpx2.RequestError, UnsafeUrlError):
    """A member-supplied MCP URL the pinned transport refused to dial."""


class SafeMCPTransport(httpx2.AsyncBaseTransport):
    """httpx2 twin of ``SafeOutboundTransport`` for the MCP SDK's client."""

    def __init__(
        self,
        policy: OutboundPolicy,
        *,
        resolve: Resolver = resolve_host,
        inner: Callable[[], httpx2.AsyncBaseTransport] | None = None,
    ) -> None:
        self._sender = PinnedSender(
            httpx2, policy, error=UnsafeMCPDestinationError, resolve=resolve, inner=inner
        )

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        return await self._sender.send(request)

    async def aclose(self) -> None:
        await self._sender.aclose()


def pinned_client_factory(
    wrapped: Callable[..., Any] | None = None,
    *,
    policy: OutboundPolicy | None = None,
    resolve: Resolver = resolve_host,
    inner: Callable[[], Any] | None = None,
) -> Callable[..., Any]:
    """An ``httpx_client_factory`` whose clients only reach vetted addresses.

    For a member-supplied (URL-type) MCP endpoint. ``wrapped`` is a caller's own
    factory that takes an ``inner`` transport, such as the payment client; its
    requests then go through ``SafeOutboundTransport``. Each call builds a fresh
    transport, because a client closes its transport on exit and the connect
    loop opens one client per transport candidate.
    """
    effective = policy or OutboundPolicy.from_env()

    def factory(
        headers: dict[str, str] | None = None,
        timeout: Any = None,
        auth: Any = None,
    ) -> Any:
        if wrapped is not None:
            return wrapped(
                headers=headers,
                timeout=timeout,
                auth=auth,
                inner=SafeOutboundTransport(effective, resolve=resolve),
            )
        kwargs: dict[str, Any] = {
            "transport": SafeMCPTransport(effective, resolve=resolve, inner=inner),
            "timeout": timeout
            or httpx2.Timeout(MCP_CONNECT_TIMEOUT_SECONDS, read=SSE_READ_TIMEOUT_SECONDS),
        }
        if headers is not None:
            kwargs["headers"] = headers
        if auth is not None:
            kwargs["auth"] = auth
        return httpx2.AsyncClient(**kwargs)

    return factory


class _ConnectedClient:
    def __init__(
        self,
        *,
        url: str,
        headers: dict[str, str] | None,
        timeout_seconds: float,
        transport: str | None,
        verdict_key: str | None,
        verdict_store: EraVerdictStore | None,
        httpx_client_factory: Callable[..., Any] | None,
    ) -> None:
        self._url = url
        self._headers = headers
        self._timeout_seconds = float(timeout_seconds)
        self._transport = transport
        self._verdict_key = verdict_key
        self._verdict_store = verdict_store
        self._httpx_client_factory = httpx_client_factory
        self._streamable_urls, self._sse_url = mcp_transport_candidates(url, transport)
        self._stack: AsyncExitStack | None = None
        self._client: Client | None = None
        self._mode = "auto"
        self._prior_discover: DiscoverResult | None = None
        self._cached = False
        self._retried = False

    @property
    def session(self):
        client = self._client
        if client is None:
            raise RuntimeError("MCP client is not connected")
        return client.session

    @property
    def protocol_version(self) -> str:
        client = self._client
        if client is None:
            raise RuntimeError("MCP client is not connected")
        return client.protocol_version

    async def __aenter__(self) -> _ConnectedClient:
        self._mode, self._prior_discover, self._cached = await _read_verdict(
            self._verdict_key, self._verdict_store
        )
        client = await self._open()
        if not self._cached:
            await _write_verdict(self._verdict_key, self._verdict_store, client)
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self._close()

    async def _close(self) -> None:
        if self._stack is not None:
            stack, self._stack = self._stack, None
            self._client = None
            await stack.aclose()

    async def _open(self) -> Client:
        last_error: BaseException | None = None
        factory = self._httpx_client_factory or create_mcp_http_client
        timeout = httpx2.Timeout(self._timeout_seconds, read=SSE_READ_TIMEOUT_SECONDS)

        for streamable_url in self._streamable_urls:
            stack = AsyncExitStack()
            try:
                http_client = factory(headers=self._headers, timeout=timeout)
                if not hasattr(http_client, "__aenter__") or not hasattr(http_client, "__aexit__"):
                    raise TypeError("httpx_client_factory must return an async context manager")
                managed_http_client = await stack.enter_async_context(http_client)
                transport = streamable_http_client(
                    streamable_url,
                    http_client=managed_http_client,
                )
                client = await stack.enter_async_context(
                    Client(
                        transport,
                        mode=self._mode,
                        prior_discover=self._prior_discover,
                        read_timeout_seconds=None,
                    )
                )
                self._stack = stack
                self._client = client
                return client
            except Exception as exc:
                last_error = exc
                await stack.aclose()
                logger.info(
                    "Streamable HTTP MCP connection failed for %s (%s), trying next transport",
                    streamable_url,
                    exc,
                )

        if self._sse_url is not None:
            stack = AsyncExitStack()
            try:
                transport = sse_client(
                    self._sse_url,
                    timeout=self._timeout_seconds,
                    sse_read_timeout=SSE_READ_TIMEOUT_SECONDS,
                    headers=self._headers,
                    httpx_client_factory=factory,
                )
                client = await stack.enter_async_context(
                    Client(
                        transport,
                        mode=self._mode,
                        prior_discover=self._prior_discover,
                        read_timeout_seconds=None,
                    )
                )
                self._stack = stack
                self._client = client
                return client
            except Exception as exc:
                last_error = exc
                await stack.aclose()

        raise last_error or RuntimeError(f"No usable MCP transport for {self._url}")

    async def _invoke(self, method: str, *args: Any, **kwargs: Any) -> Any:
        client = self._client
        if client is None:
            raise RuntimeError("MCP client is not connected")
        try:
            result = await getattr(client, method)(*args, **kwargs)
        except MCPError as exc:
            if not self._cached or self._retried or exc.code not in NEGOTIATION_ERROR_CODES:
                raise
            if self._verdict_key and self._verdict_store is not None:
                await self._verdict_store.delete(self._verdict_key)
            self._retried = True
            self._cached = False
            self._mode = "auto"
            self._prior_discover = None
            await self._close()
            client = await self._open()
            await _write_verdict(self._verdict_key, self._verdict_store, client)
            result = await getattr(client, method)(*args, **kwargs)
        return result

    async def call_tool(self, *args: Any, **kwargs: Any) -> Any:
        return await self._invoke("call_tool", *args, **kwargs)

    async def list_tools(self, *args: Any, **kwargs: Any) -> Any:
        return await self._invoke("list_tools", *args, **kwargs)


async def _read_verdict(
    verdict_key: str | None,
    verdict_store: EraVerdictStore | None,
) -> tuple[str, DiscoverResult | None, bool]:
    if not verdict_key or verdict_store is None:
        return "auto", None, False
    raw = await verdict_store.get(verdict_key)
    if raw is None:
        return "auto", None, False
    if raw == LEGACY_VERDICT:
        return "legacy", None, True
    try:
        discover = DiscoverResult.model_validate_json(raw)
    except Exception:
        logger.warning("Discarding invalid MCP era verdict for %s", verdict_key, exc_info=True)
        await verdict_store.delete(verdict_key)
        return "auto", None, False
    return MODERN_PROTOCOL_VERSION, discover, True


async def _write_verdict(
    verdict_key: str | None,
    verdict_store: EraVerdictStore | None,
    client: Client,
) -> None:
    if not verdict_key or verdict_store is None:
        return
    if client.protocol_version == MODERN_PROTOCOL_VERSION:
        discover = client.session.discover_result
        if discover is None:
            logger.warning("Modern MCP connection has no DiscoverResult; verdict not cached")
            return
        await verdict_store.set(verdict_key, discover.model_dump_json())
    else:
        await verdict_store.set(verdict_key, LEGACY_VERDICT)


@asynccontextmanager
async def connected_mcp_client(
    url: str,
    headers: Mapping[str, str] | None,
    timeout_seconds: float,
    *,
    transport: str | None = None,
    verdict_key: str | None = None,
    verdict_store: EraVerdictStore | None = None,
    httpx_client_factory: Callable[..., Any] | None = None,
) -> AsyncIterator[_ConnectedClient]:
    """Yield a connected v2 ``mcp.Client`` over streamable HTTP or SSE."""
    connected = _ConnectedClient(
        url=url,
        headers=dict(headers) if headers else None,
        timeout_seconds=timeout_seconds,
        transport=transport,
        verdict_key=verdict_key,
        verdict_store=verdict_store,
        httpx_client_factory=httpx_client_factory,
    )
    async with connected:
        yield connected
