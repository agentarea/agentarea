from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast, override
from uuid import UUID

import redis.asyncio as redis

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
    """Redis event broker using the framework-independent shared event format.

    Publishes CloudEvents-compatible messages via a raw ``redis.asyncio``
    client so Python and Go (MCP Manager) consumers read identical bytes.
    The former FastStream publish path had no Python consumer and was removed;
    every channel now goes through the single raw-redis publish.
    """

    def __init__(self, redis_client_or_url: redis.Redis | str):
        super().__init__()
        if isinstance(redis_client_or_url, str):
            self._redis_url: str | None = redis_client_or_url
            self._raw_redis: redis.Redis | None = None
        else:
            self._redis_url = None
            self._raw_redis = redis_client_or_url
        self._connected = self._raw_redis is not None

    async def _ensure_connected(self) -> None:
        """Ensure a raw Redis client exists before publishing."""
        if self._raw_redis is None:
            self._raw_redis = self._create_raw_redis()
        self._connected = True

    def _create_raw_redis(self) -> redis.Redis:
        """Create a raw Redis client from the configured URL or settings."""
        url = self._redis_url
        if url is None:
            from agentarea_common.config import get_settings

            settings = get_settings()
            url = getattr(settings.broker, "REDIS_URL", "redis://localhost:6379")
        return redis.from_url(url, decode_responses=True)

    @property
    def raw_redis(self) -> redis.Redis | None:
        """Expose the underlying raw Redis client (may be None until connected)."""
        return self._raw_redis

    async def is_connected(self) -> bool:
        """Check if the Redis client has been created."""
        return self._connected

    @override
    async def publish(self, event: DomainEvent | EventEnvelope | BaseEvent) -> None:
        """Publish an event using the shared framework-independent format.

        Converts the internal event to a CloudEvents-compatible payload and
        publishes it via raw Redis for cross-language (Go) and Python
        consumers.
        """
        await self._ensure_connected()

        event_any = cast(Any, event)
        to_envelope = getattr(event_any, "to_envelope", None)
        if callable(to_envelope):
            envelope = cast(EventEnvelope, to_envelope())
        else:
            envelope = EventEnvelope.from_any(cast(EventEnvelope | DomainEvent, event))

        channel = get_channel_for_event_type(envelope.event_type)

        shared_event = SharedEventFormat.create_event(
            event_type=envelope.event_type,
            data=envelope.data,
            source="agentarea-api",
            correlation_id=str(envelope.event_id),
            event_id=envelope.event_id,
        )

        serialized_message = SharedEventFormat.serialize(shared_event)

        logger.info(f"Publishing event to channel: {channel}")

        raw = self._raw_redis
        if raw is None:
            raise RuntimeError("Redis client is not connected")
        await raw.publish(channel, serialized_message)

    def _get_channel_for_event(self, event_type: str) -> str:
        """Get channel name for event type."""
        return get_channel_for_event_type(event_type)

    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_connected()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit with cleanup."""
        await self.close()

    async def close(self):
        """Close the raw Redis client if this broker owns it."""
        if self._raw_redis is not None and self._redis_url is not None:
            try:
                await self._raw_redis.aclose()
            except Exception as e:
                logger.warning("Error closing Redis event broker: %s", e, exc_info=True)
            finally:
                self._raw_redis = None
        self._connected = False
