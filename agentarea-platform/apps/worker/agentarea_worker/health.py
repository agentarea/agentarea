"""Health endpoint the orchestrator probes to tell a working worker from a dead one.

The worker serves no traffic, so without this a pod that crashes two seconds
after start still counts as available and a rollout retires every healthy
replica for it. Two answers:

- ``/readyz`` is 200 only after every startup dependency is initialised and each
  Temporal worker has passed its namespace check and is polling its task queue.
- ``/livez`` is 200 whenever the event loop gets to answer. It is served from
  the same loop the Temporal workers run on, so a blocked loop fails it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Protocol

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_READ_TIMEOUT_SECONDS = 5
_MAX_HEADER_LINES = 100
_REASONS = {
    200: "OK",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    503: "Service Unavailable",
}


class WorkerHealthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTAREA_WF_")

    HEALTH_PORT: int = 8081


class Poller(Protocol):
    @property
    def is_running(self) -> bool: ...


class WorkerHealth:
    def __init__(self) -> None:
        self._pollers: dict[str, Poller] = {}

    def mark_started(self, pollers: Mapping[str, Poller]) -> None:
        if not pollers:
            raise ValueError("A worker with no Temporal pollers can never be ready")
        self._pollers = dict(pollers)

    def readiness(self) -> tuple[bool, str]:
        if not self._pollers:
            return False, "starting"
        idle = sorted(name for name, poller in self._pollers.items() if not poller.is_running)
        if idle:
            return False, f"not polling: {', '.join(idle)}"
        return True, "ready"


def respond(health: WorkerHealth, method: str, path: str) -> tuple[int, str]:
    if path not in ("/livez", "/readyz"):
        return 404, "not found"
    if method != "GET":
        return 405, "method not allowed"
    if path == "/livez":
        return 200, "alive"
    ready, reason = health.readiness()
    return (200 if ready else 503), reason


class HealthServer:
    def __init__(self, health: WorkerHealth, *, host: str, port: int) -> None:
        self._health = health
        self._host = host
        self._port = port
        self._server: asyncio.Server | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("Health server is not running")
        return self._server.sockets[0].getsockname()[1]

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self._host, self._port)
        logger.info("Health endpoint listening on %s:%d (/livez, /readyz)", self._host, self.port)

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            status, body = await asyncio.wait_for(self._answer(reader), _READ_TIMEOUT_SECONDS)
            payload = body.encode()
            headers = (
                f"HTTP/1.1 {status} {_REASONS[status]}",
                "Content-Type: text/plain; charset=utf-8",
                f"Content-Length: {len(payload)}",
                "Connection: close",
            )
            writer.write("\r\n".join(headers).encode() + b"\r\n\r\n" + payload)
            await writer.drain()
        except (TimeoutError, ConnectionError, asyncio.IncompleteReadError):
            logger.debug("Health probe connection dropped", exc_info=True)
        finally:
            writer.close()

    async def _answer(self, reader: asyncio.StreamReader) -> tuple[int, str]:
        parts = (await reader.readline()).decode("latin-1").split()
        for _ in range(_MAX_HEADER_LINES):
            if (await reader.readline()) in (b"\r\n", b"\n", b""):
                break
        if len(parts) != 3:
            return 400, "bad request"
        method, target, _version = parts
        return respond(self._health, method, target.split("?", 1)[0])
