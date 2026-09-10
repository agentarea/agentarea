"""Broker configuration settings."""

from typing import Literal

from pydantic_settings import SettingsConfigDict

from .base import BaseAppSettings


class BrokerSettings(BaseAppSettings):
    """Base broker configuration."""

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_")

    BROKER: Literal["redis", "kafka"] = "redis"
    EVENT_BUS: Literal["redis", "kafka", "nats"] = "redis"


class RedisSettings(BrokerSettings):
    """Redis broker configuration."""

    REDIS_URL: str = "redis://localhost:6379"


class KafkaSettings(BrokerSettings):
    """Kafka broker configuration."""

    KAFKA_SERVERS: str = "localhost:9092"
    KAFKA_PREFIX: str = ""
