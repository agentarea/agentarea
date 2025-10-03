"""Trigger system configuration settings."""

from pydantic import Field
from pydantic_settings import BaseSettings


class TriggerSettings(BaseSettings):
    """Configuration settings for the trigger system."""

    # Failure thresholds
    TRIGGER_FAILURE_THRESHOLD: int = Field(
        default=5, description="Number of consecutive failures before auto-disabling a trigger"
    )

    # Rate limiting
    TRIGGER_MAX_EXECUTIONS_PER_HOUR: int = Field(
        default=60, description="Maximum number of executions per hour for a single trigger"
    )

    WEBHOOK_RATE_LIMIT_PER_MINUTE: int = Field(
        default=100, description="Maximum webhook requests per minute per webhook URL"
    )

    # Timeouts
    TRIGGER_EXECUTION_TIMEOUT_SECONDS: int = Field(
        default=300, description="Maximum time allowed for trigger execution (5 minutes)"
    )

    WEBHOOK_REQUEST_TIMEOUT_SECONDS: int = Field(
        default=30, description="Maximum time to wait for webhook request processing"
    )

    LLM_CONDITION_EVALUATION_TIMEOUT_SECONDS: int = Field(
        default=60, description="Maximum time for LLM condition evaluation"
    )

    # Retry settings
    TRIGGER_EXECUTION_MAX_RETRIES: int = Field(
        default=3, description="Maximum number of retries for failed trigger executions"
    )

    TRIGGER_EXECUTION_RETRY_DELAY_SECONDS: int = Field(
        default=5, description="Initial delay between trigger execution retries"
    )

    # Cleanup settings
    TRIGGER_EXECUTION_HISTORY_RETENTION_DAYS: int = Field(
        default=30, description="Number of days to retain trigger execution history"
    )

    # Health check settings
    TRIGGER_HEALTH_CHECK_INTERVAL_SECONDS: int = Field(
        default=60, description="Interval between trigger system health checks"
    )

    # Webhook settings
    WEBHOOK_BASE_URL: str = Field(
        default="/v1/webhooks", description="Base URL path for webhook endpoints"
    )

    WEBHOOK_SECRET_HEADER: str = Field(
        default="X-Webhook-Secret", description="Header name for webhook secret validation"
    )

    # Temporal settings
    TEMPORAL_SCHEDULE_NAMESPACE: str = Field(
        default="default", description="Temporal namespace for trigger schedules"
    )

    TEMPORAL_SCHEDULE_TASK_QUEUE: str = Field(
        default="trigger-schedules", description="Temporal task queue for trigger schedules"
    )

    # Feature flags
    ENABLE_LLM_CONDITIONS: bool = Field(
        default=True, description="Enable LLM-based condition evaluation"
    )

    ENABLE_WEBHOOK_VALIDATION: bool = Field(
        default=True, description="Enable webhook request validation"
    )

    ENABLE_TRIGGER_METRICS: bool = Field(
        default=True, description="Enable trigger execution metrics collection"
    )

    ENABLE_TRIGGER_SYSTEM: bool = Field(
        default=True, description="Enable the entire trigger system"
    )

    # Database settings
    TRIGGER_DB_POOL_SIZE: int = Field(
        default=10, description="Database connection pool size for trigger operations"
    )

    # Monitoring settings
    TRIGGER_METRICS_COLLECTION_INTERVAL_SECONDS: int = Field(
        default=300, description="Interval for collecting trigger execution metrics (5 minutes)"
    )

    TRIGGER_ALERT_FAILURE_RATE_THRESHOLD: float = Field(
        default=0.1, description="Failure rate threshold for triggering alerts (10%)"
    )

    model_config = {"env_prefix": "TRIGGER_", "extra": "ignore"}
