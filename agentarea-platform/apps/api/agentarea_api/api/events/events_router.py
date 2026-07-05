"""Event-bus consumer lifecycle for the API process (ADR-0018).

Consumes MCP status-change notifications from the Go MCP manager. These are
*ephemeral notifications* (Publish-Subscribe Channel): fan-out, OK to lose, no
durability needed — so they are read via the broadcast ``EventStream`` read
side (live tail), NOT the durable consumer-group ``EventSubscriber``. On
restart we tail from "now" ("$"); replaying stale statuses would be wrong.

Started/stopped from the FastAPI lifespan in ``main.py``. Publishing still
goes through the FastStream broker registered there — a separate concern,
migrated in a later increment.
"""

import asyncio
import contextlib
import logging

from agentarea_common.broker.redis_streams import RedisStreamsBroker
from agentarea_common.config import get_settings
from agentarea_common.events.adapters.redis_streams import RedisStreamsEventStream

from .mcp_events import MCP_STATUS_CHANGED_TYPE, handle_mcp_status_changed

logger = logging.getLogger(__name__)

# Backoff before reconnecting the tail after a transport error.
_RECONNECT_DELAY_SECONDS = 1.0

_broker: RedisStreamsBroker | None = None
_consumer_task: asyncio.Task[None] | None = None


def _redis_url() -> str:
    broker = get_settings().broker
    url = getattr(broker, "REDIS_URL", None)
    if not url:
        raise RuntimeError(
            "Event stream requires a Redis broker (REDIS_URL); "
            f"BROKER_TYPE={getattr(broker, 'BROKER_TYPE', 'unknown')} has none."
        )
    return url


async def _consume_mcp_status(stream: RedisStreamsEventStream) -> None:
    """Tail MCP status notifications live, surviving transient broker errors.

    A bad single event is logged and skipped (drop-ok); a transport failure
    backs off and reconnects. Cancellation propagates to stop cleanly.
    """
    while True:
        try:
            async for event in stream.read(
                stream=MCP_STATUS_CHANGED_TYPE, from_offset="$"
            ):
                try:
                    await handle_mcp_status_changed(event)
                except Exception:
                    logger.exception("MCP status handler error; dropping event")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "MCP status stream error; reconnecting in %ss", _RECONNECT_DELAY_SECONDS
            )
            await asyncio.sleep(_RECONNECT_DELAY_SECONDS)


async def start_events_router() -> None:
    """Start the background tail of MCP status notifications."""
    global _broker, _consumer_task
    if _consumer_task is not None:
        logger.warning("Events consumer already started; ignoring duplicate start")
        return

    _broker = RedisStreamsBroker(_redis_url())
    stream = RedisStreamsEventStream(_broker)
    _consumer_task = asyncio.create_task(_consume_mcp_status(stream))
    logger.info("MCP status consumer tailing %s", MCP_STATUS_CHANGED_TYPE)


async def stop_events_router() -> None:
    """Stop the background tail and close the broker connection."""
    global _broker, _consumer_task
    if _consumer_task is not None:
        _consumer_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _consumer_task
        _consumer_task = None
    if _broker is not None:
        await _broker.aclose()
        _broker = None
    logger.info("MCP status consumer stopped")
