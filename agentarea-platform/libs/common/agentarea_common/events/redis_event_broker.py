from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, override
from uuid import UUID

import redis.asyncio as redis
from faststream.redis import RedisBroker

from .base_events import DomainEvent, EventEnvelope
from .broker import EventBroker
from .shared_event_format import SharedEventFormat, get_channel_for_event_type

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
    """Redis event broker using framework-independent shared event format.

    Uses CloudEvents-compatible format for cross-language communication
    between Python services and Go MCP Manager.

    For cross-language channels (MCP events), uses raw Redis client to avoid
    FastStream binary framing. For internal channels, uses FastStream broker.
    """

    def __init__(self, redis_broker: RedisBroker):
        super().__init__()
        self.redis_broker = redis_broker
        self._connected = False
        self._raw_redis: redis.Redis | None = None

    async def _ensure_connected(self):
        """Ensure the Redis broker is connected before publishing."""
        if not self._connected:
            try:
                await self.redis_broker.connect()
                # Create raw Redis client for cross-language publishing
                # FastStream's broker adds binary framing that's incompatible with Go
                if hasattr(self.redis_broker, "_connection"):
                    conn = self.redis_broker._connection
                    if hasattr(conn, "redis"):
                        self._raw_redis = conn.redis
                    else:
                        # Fallback: create new Redis client from connection params
                        self._raw_redis = await self._create_raw_redis()
                else:
                    self._raw_redis = await self._create_raw_redis()
                self._connected = True
                logger.info("Redis event broker connected successfully")
            except Exception as e:
                logger.warning(f"Failed to connect Redis broker: {e}")
                raise

    async def _create_raw_redis(self) -> redis.Redis:
        """Create a raw Redis client for cross-language publishing."""
        from agentarea_common.config import get_settings

        settings = get_settings()
        redis_url = getattr(settings.broker, "REDIS_URL", "redis://localhost:6379")
        return redis.from_url(redis_url, decode_responses=True)

    async def is_connected(self) -> bool:
        """Check if the Redis broker is connected."""
        return self._connected

    def _is_cross_language_channel(self, channel: str) -> bool:
        """Check if channel is for cross-language communication (Go services)."""
        channel_lower = channel.lower()
        return (
            "mcp" in channel_lower
            or channel.startswith("MCPServerInstance")
        )

    @override
    async def publish(self, event: DomainEvent | EventEnvelope | BaseEvent) -> None:
        """Publish event using shared framework-independent format.

        Converts internal event format to CloudEvents-compatible format
        for cross-language compatibility with Go services.
        """
        # Ensure we're connected before publishing
        await self._ensure_connected()

        # Normalize input to EventEnvelope for type safety
        if hasattr(event, "to_envelope") and callable(event.to_envelope):
            # Supports typed Pydantic BaseEvent models without importing them here
            envelope = event.to_envelope()  # type: ignore[attr-defined]
        else:
            envelope = EventEnvelope.from_any(event)

        # Convert to shared event format (CloudEvents compatible)
        # This ensures cross-language compatibility with Go services
        channel = get_channel_for_event_type(envelope.event_type)

        shared_event = SharedEventFormat.create_event(
            event_type=envelope.event_type,
            data=envelope.data,
            source="agentarea-api",
            correlation_id=str(envelope.event_id),
            event_id=envelope.event_id,
        )

        logger.info(f"Publishing event to channel: {channel}")

        # Serialize to JSON using shared format
        serialized_message = SharedEventFormat.serialize(shared_event)

        # Publish via FastStream for internal Python consumers (SSE streaming)
        await self.redis_broker.publish(message=serialized_message, channel=channel)

        # Also publish via raw Redis for non-FastStream consumers:
        # - MCP events → Go MCP Manager
        # - Workflow events → outbound channel delivery (ChannelEventSubscriber)
        if self._raw_redis and (
            self._is_cross_language_channel(channel) or "workflow" in channel.lower()
        ):
            await self._raw_redis.publish(channel, serialized_message)

    def _get_channel_for_event(self, event_type: str) -> str:
        """Get channel name for event type."""
        return get_channel_for_event_type(event_type)

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
