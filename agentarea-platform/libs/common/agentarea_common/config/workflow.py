"""Workflow and task execution configuration."""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkflowSettings(BaseSettings):
    """Workflow execution configuration.

    EXECUTION_ENGINE determines which settings are required:
    - "temporal": all TEMPORAL_* settings must be provided (no defaults)
    - "direct": TEMPORAL_* settings are ignored
    """

    # Execution engine
    EXECUTION_ENGINE: str = "temporal"

    # Temporal settings — required when EXECUTION_ENGINE=temporal, ignored otherwise
    TEMPORAL_SERVER_URL: str = ""
    TEMPORAL_NAMESPACE: str = ""
    TEMPORAL_TASK_QUEUE: str = ""
    TEMPORAL_MAX_WORKFLOW_DURATION_DAYS: int = 7

    # Worker settings
    TEMPORAL_MAX_CONCURRENT_ACTIVITIES: int = 10
    TEMPORAL_MAX_CONCURRENT_WORKFLOWS: int = 5

    # Activity timeouts (in minutes/hours)
    AGENT_VALIDATION_TIMEOUT_MINUTES: int = 5
    AGENT_EXECUTION_TIMEOUT_HOURS: int = 24
    DYNAMIC_ACTIVITY_TIMEOUT_MINUTES: int = 30

    model_config = SettingsConfigDict(env_prefix="WORKFLOW__")

    @model_validator(mode="after")
    def validate_engine_settings(self):
        """Validate that required settings are present for the chosen engine."""
        if self.EXECUTION_ENGINE == "temporal":
            missing = []
            if not self.TEMPORAL_SERVER_URL:
                missing.append("WORKFLOW__TEMPORAL_SERVER_URL")
            if not self.TEMPORAL_NAMESPACE:
                missing.append("WORKFLOW__TEMPORAL_NAMESPACE")
            if not self.TEMPORAL_TASK_QUEUE:
                missing.append("WORKFLOW__TEMPORAL_TASK_QUEUE")
            if missing:
                raise ValueError(f"EXECUTION_ENGINE=temporal requires: {', '.join(missing)}")
        elif self.EXECUTION_ENGINE not in ("temporal", "direct"):
            raise ValueError(
                f"Unknown EXECUTION_ENGINE '{self.EXECUTION_ENGINE}'. Must be 'temporal' or 'direct'."
            )
        return self


class TaskExecutionSettings(BaseSettings):
    """Task execution configuration."""

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
