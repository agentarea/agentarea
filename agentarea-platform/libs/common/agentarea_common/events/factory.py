"""Event-bus backend factory.

Selects the concrete :class:`EventBroker` implementation from the
``EVENT_BUS_BACKEND`` setting. Redis is the open-source default; ``kafka`` and
``nats`` are reserved for future/enterprise backends and raise explicitly
rather than silently falling back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .broker import EventBroker
from .redis_event_broker import RedisEventBroker

if TYPE_CHECKING:
    from agentarea_common.config.broker import KafkaSettings, RedisSettings


def create_event_broker(
    broker_settings: RedisSettings | KafkaSettings,
) -> EventBroker:
    """Create the event broker for the configured ``EVENT_BUS_BACKEND``.

    Args:
        broker_settings: The resolved broker settings (Redis or Kafka).

    Returns:
        A concrete :class:`EventBroker`.

    Raises:
        NotImplementedError: For backends other than ``redis``.
    """
    backend = getattr(broker_settings, "EVENT_BUS_BACKEND", "redis")

    if backend == "redis":
        redis_url = getattr(broker_settings, "REDIS_URL", "redis://localhost:6379")
        return RedisEventBroker(redis_url)

    if backend in ("kafka", "nats"):
        raise NotImplementedError(
            f"EVENT_BUS_BACKEND='{backend}' is not implemented. Only 'redis' is currently"
            " supported; Kafka/NATS are reserved for a future/enterprise backend."
        )

    raise NotImplementedError(f"Unknown EVENT_BUS_BACKEND='{backend}'")
