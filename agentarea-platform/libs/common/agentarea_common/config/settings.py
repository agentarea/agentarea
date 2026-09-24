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
from .keto import KetoSettings
from .mcp import MCPSettings
from .observability import ObservabilitySettings
from .openfga import OpenFGASettings
from .secrets import SecretManagerSettings
from .triggers import TriggerSettings
from .workflow import WorkflowSettings


class Settings(BaseSettings):
    """Main application settings container."""

    database: DatabaseSettings
    aws: AWSSettings
    app: AppSettings
    secret_manager: SecretManagerSettings
    broker: RedisSettings | KafkaSettings
    mcp: MCPSettings
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    workflow: WorkflowSettings = Field(default_factory=WorkflowSettings)
    triggers: TriggerSettings = Field(default_factory=TriggerSettings)
    channel_delivery: ChannelDeliverySettings = Field(default_factory=ChannelDeliverySettings)
    access_control: AccessControlSettings = Field(default_factory=AccessControlSettings)
    keto: KetoSettings = Field(default_factory=KetoSettings)
    openfga: OpenFGASettings = Field(default_factory=OpenFGASettings)

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
        observability=ObservabilitySettings(),
        workflow=WorkflowSettings(),
        triggers=TriggerSettings(),
        channel_delivery=ChannelDeliverySettings(),
        access_control=AccessControlSettings(),
        keto=KetoSettings(),
        openfga=OpenFGASettings(),
    )
