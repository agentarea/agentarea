from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, override
from uuid import UUID

from faststream.redis import RedisBroker

from .base_events import DomainEvent, EventEnvelope
from .broker import EventBroker

if TYPE_CHECKING:
    from .event_models import BaseEvent

logger = logging.getLogger(__name__)


class JSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles datetime and UUID objects."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


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

    async def is_connected(self) -> bool:
        """Check if the Redis broker is connected."""
        return self._connected

    @override
    async def publish(self, event: DomainEvent | EventEnvelope | BaseEvent) -> None:
        # Ensure we're connected before publishing
        await self._ensure_connected()

        # Normalize input to EventEnvelope for type safety
        if hasattr(event, "to_envelope") and callable(event.to_envelope):
            # Supports typed Pydantic BaseEvent models without importing them here
            envelope = event.to_envelope()  # type: ignore[attr-defined]
        else:
            envelope = EventEnvelope.from_any(event)  # DomainEvent | EventEnvelope | dict

        # Then publish to Redis for distributed subscribers
        # Keep timestamp as unix float for backward compatibility
        event_data: dict[str, Any] = {
            "event_id": str(envelope.event_id),
            "timestamp": str(envelope.timestamp.timestamp()),
            "event_type": envelope.event_type,
            "data": envelope.data,
        }
        channel = self._get_channel_for_event(envelope.event_type)

        logger.info(f"Publishing event to channel: {channel}")

        # JSON-serialize the message using custom encoder to handle datetime/UUID objects
        # This ensures proper UTF-8 encoding and handles non-primitive types
        serialized_message = json.dumps(event_data, cls=JSONEncoder)
        await self.redis_broker.publish(message=serialized_message, channel=channel)

    def _get_channel_for_event(self, event_type: str) -> str:
        return event_type

    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_connected()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit with thorough cleanup."""
        if self._connected:
            try:
                # Close the Redis broker
                await self.redis_broker.close()
                self._connected = False
                logger.info("Redis event broker disconnected")
            except Exception as e:
                logger.warning(f"Error closing Redis event broker: {e}")

        # Additional cleanup for any remaining connections
        try:
            if hasattr(self.redis_broker, "_connection") and self.redis_broker._connection:
                await self.redis_broker._connection.close()
        except Exception as e:
            logger.debug(f"Error during additional Redis cleanup: {e}")

    async def close(self):
        """Explicit close method for manual cleanup."""
        await self.__aexit__(None, None, None)
