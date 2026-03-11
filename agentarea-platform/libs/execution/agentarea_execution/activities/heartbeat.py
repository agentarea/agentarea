"""Auto-heartbeater decorator for long-running Temporal activities.

Ported from Temporal's OpenAI Agents SDK integration pattern.
Background asyncio task heartbeats at heartbeat_timeout / 2 frequency,
enabling:
- Fast worker crash detection during long LLM calls
- Cancellation signal delivery to running activities
"""

import asyncio
from collections.abc import Callable
from functools import wraps
from typing import Any

from temporalio import activity


async def _heartbeat_every(delay: float) -> None:
    """Send heartbeat at regular intervals."""
    while True:
        await asyncio.sleep(delay)
        activity.heartbeat()


def auto_heartbeater[F: Callable[..., Any]](fn: F) -> F:
    """Decorator that auto-heartbeats during long-running activities.

    If heartbeat_timeout is configured on the activity execution,
    sends heartbeats at twice the frequency of the timeout.
    If no heartbeat_timeout is set, the activity runs without heartbeating.
    """

    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        heartbeat_timeout = activity.info().heartbeat_timeout
        heartbeat_task = None
        if heartbeat_timeout:
            heartbeat_task = asyncio.create_task(
                _heartbeat_every(heartbeat_timeout.total_seconds() / 2)
            )
        try:
            return await fn(*args, **kwargs)
        finally:
            if heartbeat_task:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

    return wrapper  # type: ignore[return-value]
