"""Broker abstraction for durable streams (Redis Streams now, Kafka later)."""

from .dedup import DedupCache
from .interface import BrokerClient, BrokerMessage
from .redis_streams import RedisStreamsBroker

__all__ = [
    "BrokerClient",
    "BrokerMessage",
    "DedupCache",
    "RedisStreamsBroker",
]
