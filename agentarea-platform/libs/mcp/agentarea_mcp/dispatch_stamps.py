"""The last real call to each MCP instance, stamped off the call path.

A tool call only queues its outcome (``record_dispatch``); a ``DispatchStampWriter``
started by the process that makes the calls writes the queue to
``mcp_server_instances.last_dispatch``. A process that calls tools without running
the writer records nothing, which is why the API and the worker each run one.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from agentarea_common.base.tenant_scope import unscoped
from prometheus_client import Counter
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.domain.verification_types import VERIFICATION_SCHEMA_VERSION

logger = logging.getLogger(__name__)

_dropped_total = Counter(
    "mcp_last_dispatch_dropped_total",
    "Number of last_dispatch writes dropped due to full queue",
)

_pending: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=1000)


def record_dispatch(instance_id: UUID | str, error: str | None = None) -> None:
    """Queue the outcome of a call to ``instance_id``; ``error`` marks it failed.

    Runs on the call path, so it never blocks and never raises.
    """
    stamp = {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "status": "failed" if error is not None else "succeeded",
        "at": datetime.now(UTC).isoformat(),
        "error": error,
    }
    try:
        _pending.put_nowait((str(instance_id), stamp))
    except asyncio.QueueFull:
        _dropped_total.inc()


class DispatchStampWriter:
    """Writes queued dispatch stamps every ``interval`` seconds, and once more on stop."""

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        interval: float = 0.5,
        batch_size: int = 100,
    ) -> None:
        self._session_factory = session_factory
        self._interval = interval
        self._batch_size = batch_size
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="mcp-dispatch-stamps")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        while await self.flush():
            pass

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            await self.flush()

    async def flush(self) -> int:
        """Write one batch; returns how many stamps it took off the queue."""
        latest: dict[UUID, dict[str, Any]] = {}
        taken = 0
        while taken < self._batch_size and not _pending.empty():
            instance_id, stamp = _pending.get_nowait()
            taken += 1
            try:
                latest[UUID(instance_id)] = stamp
            except ValueError:
                logger.exception(
                    "Dropping a dispatch stamp for malformed instance id %r", instance_id
                )
        if not latest:
            return taken
        try:
            async with self._session_factory() as session:
                with unscoped("the batch holds dispatch stamps queued by calls in any workspace"):
                    for instance_id, stamp in latest.items():
                        await session.execute(
                            update(MCPServerInstance)
                            .where(MCPServerInstance.id == instance_id)
                            .values(last_dispatch=stamp, updated_at=MCPServerInstance.updated_at)
                        )
                await session.commit()
        except Exception:
            logger.error("Writing %d MCP dispatch stamps failed", len(latest), exc_info=True)
        return taken
