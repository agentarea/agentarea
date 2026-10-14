"""Auto-heartbeater decorator for long-running Temporal activities.

Ported from Temporal's OpenAI Agents SDK integration pattern.
Background asyncio task heartbeats at heartbeat_timeout / 2 frequency,
enabling:
- Fast worker crash detection during long LLM calls
- Cancellation signal delivery to running activities
"""

import asyncio
from collections.abc import Callable, Coroutine
from datetime import timedelta
from functools import wraps
from typing import Any

from temporalio import activity

# How soon a running activity hears that it was cancelled: cancellation only
# reaches it in the answer to a heartbeat, so it heartbeats this often and the
# worker sends each one on (its throttle is set to the same interval).
CANCELLATION_DELIVERY_INTERVAL = timedelta(seconds=2)


async def _heartbeat_every(delay: float) -> None:
    """Send heartbeat at regular intervals."""
    while True:
        await asyncio.sleep(delay)
        activity.heartbeat()


def auto_heartbeater[**P, R](
    fn: Callable[P, Coroutine[Any, Any, R]],
) -> Callable[P, Coroutine[Any, Any, R]]:
    """Decorator that auto-heartbeats during long-running activities.

    If heartbeat_timeout is configured on the activity execution, sends
    heartbeats at twice the frequency of the timeout, and at least every
    CANCELLATION_DELIVERY_INTERVAL so a stop reaches the activity promptly.
    If no heartbeat_timeout is set, the activity runs without heartbeating.
    """

    @wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        heartbeat_timeout = activity.info().heartbeat_timeout
        heartbeat_task = None
        if heartbeat_timeout:
            heartbeat_task = asyncio.create_task(
                _heartbeat_every(
                    min(
                        heartbeat_timeout.total_seconds() / 2,
                        CANCELLATION_DELIVERY_INTERVAL.total_seconds(),
                    )
                )
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

    return wrapper
