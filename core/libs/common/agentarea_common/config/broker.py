"""Broker configuration settings."""

from typing import Literal

from .base import BaseAppSettings


class BrokerSettings(BaseAppSettings):
    """Base broker configuration."""

    BROKER_TYPE: Literal["redis", "kafka"] = "redis"


class RedisSettings(BrokerSettings):
    """Redis broker configuration."""

    REDIS_URL: str = "redis://localhost:6379"


class KafkaSettings(BrokerSettings):
    """Kafka broker configuration."""

    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_TOPIC_PREFIX: str = ""
