import logging
from typing import Any, Dict, override
from faststream.redis import RedisBroker

from .broker import EventBroker
from .base_events import DomainEvent

logger = logging.getLogger(__name__)


class RedisEventBroker(EventBroker):
    def __init__(self, redis_broker: RedisBroker):
        super().__init__()
        self.redis_broker = redis_broker

    @override
    async def publish(self, event: DomainEvent):
        # Then publish to Redis for distributed subscribers
        event_data: Dict[str, Any] = {
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
