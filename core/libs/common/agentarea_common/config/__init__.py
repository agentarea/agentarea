"""Configuration management for AgentArea application.

This module provides centralized configuration management with clean separation
of concerns across different settings domains.
"""

from .app import AppSettings
from .aws import AWSSettings, get_aws_settings, get_s3_client
from .base import BaseAppSettings
from .broker import BrokerSettings, KafkaSettings, RedisSettings
from .database import Database, DatabaseSettings, get_database, get_db, get_db_settings, get_sync_db
from .mcp import MCPManagerSettings, MCPSettings
from .secrets import SecretManagerSettings, get_secret_manager_settings
from .settings import Settings, get_settings
from .triggers import TriggerSettings
from .workflow import TaskExecutionSettings, WorkflowSettings

__all__ = [
    # Base
    "BaseAppSettings",
    # Main settings
    "Settings",
    "get_settings",
    # Database
    "DatabaseSettings",
    "get_db_settings",
    "Database",
    "get_database",
    "get_db",
    "get_sync_db",
    # AWS
    "AWSSettings",
    "get_aws_settings",
    "get_s3_client",
    # App
    "AppSettings",
    # Broker
    "BrokerSettings",
    "RedisSettings",
    "KafkaSettings",
    # MCP
    "MCPSettings",
    "MCPManagerSettings",
    # Secrets
    "SecretManagerSettings",
    "get_secret_manager_settings",
    # Triggers
    "TriggerSettings",
    # Workflow
    "WorkflowSettings",
    "TaskExecutionSettings",
]
