"""Main application settings container."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings

from .access_control import AccessControlSettings
from .app import AppSettings
from .aws import AWSSettings
from .broker import BrokerSettings, KafkaSettings, RedisSettings
from .channels import ChannelDeliverySettings
from .database import DatabaseSettings
from .http import HttpSettings
from .mcp import MCPSettings
from .observability import ObservabilitySettings
from .openfga import OpenFGASettings
from .sandbox import SandboxSettings
from .secrets import SecretManagerSettings
from .streams import EventStreamSettings
from .temporal import TemporalSettings
from .triggers import TriggerSettings


class Settings(BaseSettings):
    """Main application settings container."""

    database: DatabaseSettings
    aws: AWSSettings
    app: AppSettings
    secret_manager: SecretManagerSettings
    broker: RedisSettings | KafkaSettings
    mcp: MCPSettings
    http: HttpSettings = Field(default_factory=HttpSettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    temporal: TemporalSettings = Field(default_factory=TemporalSettings)
    triggers: TriggerSettings = Field(default_factory=TriggerSettings)
    channel_delivery: ChannelDeliverySettings = Field(default_factory=ChannelDeliverySettings)
    access_control: AccessControlSettings = Field(default_factory=AccessControlSettings)
    openfga: OpenFGASettings = Field(default_factory=OpenFGASettings)
    streams: EventStreamSettings = Field(default_factory=EventStreamSettings)

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    """Get the main application settings."""
    broker_type = BrokerSettings().BROKER
    broker = RedisSettings() if broker_type == "redis" else KafkaSettings()

    return Settings(
        database=DatabaseSettings(),
        aws=AWSSettings(),
        app=AppSettings(),
        secret_manager=SecretManagerSettings(),
        broker=broker,
        mcp=MCPSettings(),
        http=HttpSettings(),
        sandbox=SandboxSettings(),
        observability=ObservabilitySettings(),
        temporal=TemporalSettings(),
        triggers=TriggerSettings(),
        channel_delivery=ChannelDeliverySettings(),
        access_control=AccessControlSettings(),
        openfga=OpenFGASettings(),
        streams=EventStreamSettings(),
    )
