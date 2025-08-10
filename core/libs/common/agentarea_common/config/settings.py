"""Main application settings container."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings

from .app import AppSettings
from .aws import AWSSettings
from .broker import BrokerSettings, KafkaSettings, RedisSettings
from .database import DatabaseSettings
from .mcp import MCPManagerSettings, MCPSettings
from .secrets import SecretManagerSettings
from .triggers import TriggerSettings
from .workflow import TaskExecutionSettings, WorkflowSettings


class Settings(BaseSettings):
    """Main application settings container."""

    database: DatabaseSettings
    aws: AWSSettings
    app: AppSettings
    secret_manager: SecretManagerSettings
    broker: RedisSettings | KafkaSettings
    mcp: MCPSettings
    mcp_manager: MCPManagerSettings = Field(default_factory=MCPManagerSettings)
    workflow: WorkflowSettings = Field(default_factory=WorkflowSettings)
    task_execution: TaskExecutionSettings = Field(default_factory=TaskExecutionSettings)
    triggers: TriggerSettings = Field(default_factory=TriggerSettings)

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    """Get the main application settings."""
    broker_type = BrokerSettings().BROKER_TYPE
    broker = RedisSettings() if broker_type == "redis" else KafkaSettings()

    return Settings(
        database=DatabaseSettings(),
        aws=AWSSettings(),
        app=AppSettings(),
        secret_manager=SecretManagerSettings(),
        broker=broker,
        mcp=MCPSettings(),
        mcp_manager=MCPManagerSettings(),
        workflow=WorkflowSettings(),
        task_execution=TaskExecutionSettings(),
        triggers=TriggerSettings(),
    )
