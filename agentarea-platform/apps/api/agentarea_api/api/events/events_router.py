"""Event-bus consumer lifecycle for the API process (ADR-0018).

Owns the subscription that consumes MCP status-change events from the Go MCP
manager over Redis Streams via the broker-neutral ``RedisStreamsEventBus``.
Started/stopped from the FastAPI lifespan in ``main.py``.

Publishing still goes through the FastStream broker registered in ``main.py``;
that is a separate concern and is migrated in a later increment.
"""

import logging

from agentarea_common.broker.redis_streams import RedisStreamsBroker
from agentarea_common.config import get_settings
from agentarea_common.events.adapters.redis_streams import RedisStreamsEventBus
from agentarea_common.events.ports import Subscription

from .mcp_events import MCP_STATUS_CHANGED_TYPE, handle_mcp_status_changed

logger = logging.getLogger(__name__)

# Durable consumer group for the API; competing API replicas share the group.
_CONSUMER_GROUP = "agentarea-api"

_broker: RedisStreamsBroker | None = None
_subscription: Subscription | None = None


def _redis_url() -> str:
    broker = get_settings().broker
    url = getattr(broker, "REDIS_URL", None)
    if not url:
        raise RuntimeError(
            "Event bus requires a Redis broker (REDIS_URL); "
            f"BROKER_TYPE={getattr(broker, 'BROKER_TYPE', 'unknown')} has none."
        )
    return url


async def start_events_router() -> None:
    """Subscribe the API to MCP status-change events on the Redis Streams bus."""
    global _broker, _subscription
    if _subscription is not None:
        logger.warning("Events consumer already started; ignoring duplicate start")
        return

    _broker = RedisStreamsBroker(_redis_url())
    bus = RedisStreamsEventBus(_broker)
    _subscription = await bus.subscribe(
        topic=MCP_STATUS_CHANGED_TYPE,
        group=_CONSUMER_GROUP,
        handler=handle_mcp_status_changed,
    )
    logger.info("Events consumer subscribed on %s", MCP_STATUS_CHANGED_TYPE)


async def stop_events_router() -> None:
    """Stop the subscription and close the broker connection."""
    global _broker, _subscription
    if _subscription is not None:
        await _subscription.stop()
        _subscription = None
    if _broker is not None:
        await _broker.aclose()
        _broker = None
    logger.info("Events consumer stopped")
