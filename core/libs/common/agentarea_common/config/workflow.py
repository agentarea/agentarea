"""Workflow and task execution configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkflowSettings(BaseSettings):
    """Workflow execution configuration."""

    # Temporal-specific settings
    TEMPORAL_SERVER_URL: str
    TEMPORAL_NAMESPACE: str
    TEMPORAL_TASK_QUEUE: str
    TEMPORAL_MAX_WORKFLOW_DURATION_DAYS: int = 7

    # Worker settings
    TEMPORAL_MAX_CONCURRENT_ACTIVITIES: int = 10
    TEMPORAL_MAX_CONCURRENT_WORKFLOWS: int = 5

    # Activity timeouts (in minutes/hours)
    AGENT_VALIDATION_TIMEOUT_MINUTES: int = 5
    AGENT_EXECUTION_TIMEOUT_HOURS: int = 24
    DYNAMIC_ACTIVITY_TIMEOUT_MINUTES: int = 30

    model_config = SettingsConfigDict(env_prefix="WORKFLOW__")


class TaskExecutionSettings(BaseSettings):
    """Task execution configuration."""

    # New execution mode (legacy mode removed)
    USE_LEGACY_TASK_EXECUTION: bool = False

    # Default task parameters
    DEFAULT_TASK_RETRY_ATTEMPTS: int = 3
    DEFAULT_TASK_TIMEOUT_HOURS: int = 24
    TASK_HEARTBEAT_INTERVAL_SECONDS: int = 30

    # Dynamic activity discovery
    ENABLE_DYNAMIC_ACTIVITY_DISCOVERY: bool = True
    MAX_DISCOVERED_ACTIVITIES_PER_TASK: int = 10

    # Budget and cost management
    DEFAULT_TASK_BUDGET_USD: float = 1.0  # Default $1 per task
    ENABLE_BUDGET_ENFORCEMENT: bool = True
    BUDGET_PAUSE_ON_EXCEEDED: bool = True
    BUDGET_SAFETY_MARGIN: float = 0.1  # 10% safety margin before pause

    model_config = SettingsConfigDict(env_prefix="TASK__")
