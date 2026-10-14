"""Relaying an MCP server's progress notifications as ``tool.progress`` task events."""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from agentarea_mcp.tool_context import ProgressCallback

logger = logging.getLogger(__name__)

# At most two events per second per call; a server may notify far more often.
TOOL_PROGRESS_MIN_INTERVAL_SECONDS = 0.5


def make_tool_progress_relay(
    *,
    record: Callable[[dict[str, Any]], Awaitable[None]],
    task_id: str,
    tool_name: str,
    tool_call_id: str,
    heartbeat: Callable[[], None],
    min_interval_seconds: float = TOOL_PROGRESS_MIN_INTERVAL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> ProgressCallback:
    """A progress callback that heartbeats on every notification and records
    at most one event per ``min_interval_seconds``.

    A notification inside the window is dropped, except one that reports
    completion (``progress >= total``). A failed write is logged, never raised:
    progress is advisory and must not fail the tool call.
    """
    recorded_at: float | None = None

    async def relay(progress: float, total: float | None, message: str | None) -> None:
        nonlocal recorded_at
        try:
            heartbeat()
        except Exception:
            logger.debug("Heartbeat on tool progress failed", exc_info=True)

        now = clock()
        finished = total is not None and progress >= total
        if recorded_at is not None and now - recorded_at < min_interval_seconds and not finished:
            return
        recorded_at = now
        try:
            await record(
                {
                    "task_id": task_id,
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "progress": progress,
                    "total": total,
                    "message": message,
                }
            )
        except Exception:
            logger.warning(
                "Failed to record progress of tool call %s in task %s",
                tool_call_id,
                task_id,
                exc_info=True,
            )

    return relay
