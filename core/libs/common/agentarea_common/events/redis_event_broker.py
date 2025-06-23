import logging
from typing import Any, override

from faststream.redis import RedisBroker

from .base_events import DomainEvent
from .broker import EventBroker

logger = logging.getLogger(__name__)


class RedisEventBroker(EventBroker):
    def __init__(self, redis_broker: RedisBroker):
        super().__init__()
        self.redis_broker = redis_broker
        self._connected = False

    async def _ensure_connected(self):
        """Ensure the Redis broker is connected before publishing."""
        if not self._connected:
            try:
                await self.redis_broker.connect()
                self._connected = True
                logger.info("Redis event broker connected successfully")
            except Exception as e:
                logger.warning(f"Failed to connect Redis event broker: {e}")
                raise

    @override
    async def publish(self, event: DomainEvent):
        # Ensure we're connected before publishing
        await self._ensure_connected()

        # Then publish to Redis for distributed subscribers
        event_data: dict[str, Any] = {
            "event_id": str(event.event_id),
            "timestamp": str(event.timestamp.timestamp()),
            "event_type": event.event_type,
            "data": event.data,
        }
        channel = self._get_channel_for_event(event.event_type)

        logger.info(f"Publishing event to channel: {channel}")

        await self.redis_broker.publish(message=event_data, channel=channel)

    def _get_channel_for_event(self, event_type: str) -> str:
        return event_type

    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_connected()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._connected:
            try:
                await self.redis_broker.close()
                self._connected = False
                logger.info("Redis event broker disconnected")
            except Exception as e:
                logger.warning(f"Error closing Redis event broker: {e}")
