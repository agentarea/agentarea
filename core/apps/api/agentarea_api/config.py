"""Config module for AgentArea API application.

This module re-exports configuration from the common library.
"""

from agentarea_common.config import *  # noqa: F403

__all__ = [
    "AWSSettings",
    "AppSettings",
    "BaseAppSettings",
    "BrokerSettings",
    "Database",
    "DatabaseSettings",
    "KafkaSettings",
    "MCPManagerSettings",
    "MCPSettings",
    "RedisSettings",
    "SecretManagerSettings",
    "Settings",
    "TaskExecutionSettings",
    "WorkflowSettings",
    "get_app_settings",
    "get_aws_settings",
    "get_database",
    "get_db",
    "get_db_settings",
    "get_s3_client",
    "get_secret_manager_settings",
    "get_settings",
    "get_sync_db",
]
