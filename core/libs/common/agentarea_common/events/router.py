from agentarea_common.config import KafkaSettings, RedisSettings
from faststream.redis.fastapi import RedisRouter

from .redis_event_broker import RedisEventBroker


def get_event_router(
    settings: RedisSettings | KafkaSettings,
) -> RedisRouter:
    """Factory function to create and configure an event router.

    Args:
        settings: Broker settings (Redis or Kafka)

    Returns:
        Configured RedisRouter instance

    Raises:
        ValueError: If settings type is not supported or if Kafka is used (not implemented)
    """
    if hasattr(settings, "REDIS_URL"):
        # Redis settings
        router = RedisRouter(settings.REDIS_URL)  # type: ignore
        return router
    elif hasattr(settings, "KAFKA_BOOTSTRAP_SERVERS"):
        # Kafka settings - not implemented yet
        raise ValueError(
            "Kafka broker is not yet implemented. Please use Redis settings. "
            "To implement Kafka support, install faststream[kafka] and update this function."
        )
    else:
        raise ValueError(f"Unsupported broker settings type: {type(settings)}")


def create_event_broker_from_router(router: RedisRouter) -> RedisEventBroker:
    """Create an EventBroker instance from a router's underlying broker.

    This ensures the EventBroker uses the same broker instance as the router.

    Args:
        router: RedisRouter instance

    Returns:
        RedisEventBroker that uses the same broker as the router
    """
    # Get the underlying RedisBroker from the router
    redis_broker = router.broker
    return RedisEventBroker(redis_broker)
