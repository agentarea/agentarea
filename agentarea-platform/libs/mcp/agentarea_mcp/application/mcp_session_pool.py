"""Connected MCP clients kept between tool calls, one process at a time.

Opening a client costs a TCP/TLS handshake and an MCP negotiation (``initialize``
or ``server/discover``); a run that calls the same server ten times paid that ten
times. A pooled client is reused only by a call with the same address, the same
headers (so the same credential), the same egress and the same timeout, and only
by one call at a time. A header that belongs to one call, such as its signed
context, is never part of the client: it rides on that call's requests only
(``mcp_client.call_headers``).
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import weakref
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass

from .mcp_client import ConnectedMCPClient

logger = logging.getLogger(__name__)

# How long an unused client stays open. Below the idle limits servers and proxies
# commonly apply, so a reused session is rarely one the other side already dropped.
POOL_IDLE_SECONDS = 60.0
POOL_MAX_IDLE_PER_KEY = 4
POOL_MAX_IDLE = 64

OpenClient = Callable[[], AbstractAsyncContextManager[ConnectedMCPClient]]


@dataclass(frozen=True)
class SessionKey:
    """What a pooled client was opened with; a call reuses one only on a full match."""

    url: str
    transport: str | None
    headers_digest: str
    egress: str
    verdict_key: str | None
    timeout_seconds: float


def session_key(
    url: str,
    headers: Mapping[str, str] | None,
    *,
    transport: str | None,
    egress: str,
    verdict_key: str | None,
    timeout_seconds: float,
) -> SessionKey:
    canonical = json.dumps(sorted((headers or {}).items()), separators=(",", ":"))
    return SessionKey(
        url=url,
        transport=transport,
        headers_digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        egress=egress,
        verdict_key=verdict_key,
        timeout_seconds=float(timeout_seconds),
    )


class _Session:
    """One connected client, owned by a task of its own.

    The client's transport is a stack of anyio task groups, which must be left
    by the task that entered them; the call that opens a client is gone long
    before the client closes. The owner task starts from an empty context, so
    nothing of the first caller (its activity, its call headers) reaches the
    client's background requests.
    """

    def __init__(self, open_client: OpenClient) -> None:
        self.client: ConnectedMCPClient | None = None
        self.reused = False
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._error: BaseException | None = None
        self.expiry: asyncio.TimerHandle | None = None
        self.idle_since = 0.0
        self._task = asyncio.create_task(self._own(open_client), context=contextvars.Context())

    async def _own(self, open_client: OpenClient) -> None:
        try:
            async with open_client() as client:
                self.client = client
                self._ready.set()
                await self._stop.wait()
        except asyncio.CancelledError as exc:
            self._error = exc
            logger.debug("Pooled MCP client cancelled", exc_info=True)
        except BaseException as exc:
            self._error = exc
            if self._ready.is_set():
                logger.warning("Pooled MCP client closed with an error", exc_info=True)
        finally:
            self.client = None
            self._ready.set()

    async def ready(self) -> ConnectedMCPClient:
        await self._ready.wait()
        client = self.client
        if client is None:
            raise self._error or RuntimeError("MCP client closed before it connected")
        return client

    @property
    def alive(self) -> bool:
        return self.client is not None and not self._stop.is_set()

    def retire(self) -> None:
        """Do not reuse this connection: the lease closes it when it ends."""
        self._stop.set()

    async def aclose(self) -> None:
        if self.expiry is not None:
            self.expiry.cancel()
            self.expiry = None
        self._stop.set()
        if not self._ready.is_set():
            self._task.cancel()
        await asyncio.wait([self._task])


class MCPSessionPool:
    """Idle connected clients by ``SessionKey``, bounded and expiring."""

    def __init__(
        self,
        *,
        idle_seconds: float = POOL_IDLE_SECONDS,
        max_idle_per_key: int = POOL_MAX_IDLE_PER_KEY,
        max_idle: int = POOL_MAX_IDLE,
    ) -> None:
        self._idle_seconds = idle_seconds
        self._max_idle_per_key = max_idle_per_key
        self._max_idle = max_idle
        self._idle: dict[SessionKey, list[_Session]] = {}
        self._closing: set[asyncio.Task[None]] = set()

    @property
    def idle_count(self) -> int:
        return sum(len(sessions) for sessions in self._idle.values())

    @asynccontextmanager
    async def lease(self, key: SessionKey, open_client: OpenClient) -> AsyncIterator[_Session]:
        """A connected session for one call: an idle one for ``key``, or a new one.

        It goes back to the pool when the call returns, and is closed when the
        call raises, since the connection's state is then unknown.
        """
        session = self._take(key)
        if session is None:
            session = _Session(open_client)
        try:
            await session.ready()
        except BaseException:
            self._close(session)
            raise
        returned = False
        try:
            yield session
            returned = True
        finally:
            if returned and session.alive:
                self._put(key, session)
            else:
                self._close(session)

    def _take(self, key: SessionKey) -> _Session | None:
        sessions = self._idle.get(key)
        while sessions:
            session = sessions.pop()
            if session.expiry is not None:
                session.expiry.cancel()
                session.expiry = None
            if session.alive:
                if not sessions:
                    del self._idle[key]
                session.reused = True
                return session
            self._close(session)
        self._idle.pop(key, None)
        return None

    def _put(self, key: SessionKey, session: _Session) -> None:
        sessions = self._idle.setdefault(key, [])
        sessions.append(session)
        loop = asyncio.get_running_loop()
        session.idle_since = loop.time()
        session.expiry = loop.call_later(self._idle_seconds, self._expire, key, session)
        while len(sessions) > self._max_idle_per_key:
            self._close(sessions.pop(0))
        while self.idle_count > self._max_idle:
            self._evict_oldest()

    def _evict_oldest(self) -> None:
        oldest_key = min(self._idle, key=lambda k: self._idle[k][0].idle_since)
        sessions = self._idle[oldest_key]
        self._close(sessions.pop(0))
        if not sessions:
            del self._idle[oldest_key]

    def _expire(self, key: SessionKey, session: _Session) -> None:
        session.expiry = None
        sessions = self._idle.get(key)
        if sessions and session in sessions:
            sessions.remove(session)
            if not sessions:
                del self._idle[key]
            self._close(session)

    def _close(self, session: _Session) -> None:
        task = asyncio.get_running_loop().create_task(session.aclose())
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    async def aclose(self) -> None:
        """Close every idle client and wait for all closes to finish."""
        for sessions in self._idle.values():
            for session in sessions:
                self._close(session)
        self._idle.clear()
        if self._closing:
            await asyncio.wait(list(self._closing))


_pools: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, MCPSessionPool] = (
    weakref.WeakKeyDictionary()
)


def session_pool() -> MCPSessionPool:
    """This event loop's pool: its clients belong to the loop that opened them."""
    loop = asyncio.get_running_loop()
    pool = _pools.get(loop)
    if pool is None:
        pool = _pools[loop] = MCPSessionPool()
    return pool
