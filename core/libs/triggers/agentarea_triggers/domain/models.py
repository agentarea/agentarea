"""Trigger domain models."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from .enums import ExecutionStatus, TriggerType, WebhookType


class Trigger(BaseModel):
    """Base trigger domain model."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=1000)
    agent_id: UUID
    trigger_type: TriggerType
    is_active: bool = True
    task_parameters: dict[str, Any] = Field(default_factory=dict)
    conditions: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str
    workspace_id: str | None = None

    # Business logic safety
    failure_threshold: int = Field(default=5, ge=1, le=100)
    consecutive_failures: int = Field(default=0, ge=0)
    last_execution_at: datetime | None = None

    class Config:
        """Pydantic model configuration."""

        from_attributes = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate trigger name."""
        if not v.strip():
            raise ValueError("Trigger name cannot be empty")
        return v.strip()

    @model_validator(mode="after")
    def validate_datetime_fields(self) -> "Trigger":
        """Validate datetime field relationships."""
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be before created_at")

        if self.last_execution_at and self.last_execution_at < self.created_at:
            raise ValueError("last_execution_at cannot be before created_at")

        return self

    def should_disable_due_to_failures(self) -> bool:
        """Check if trigger should be disabled due to consecutive failures."""
        return self.consecutive_failures >= self.failure_threshold

    def record_execution_success(self) -> None:
        """Record successful execution."""
        self.last_execution_at = datetime.utcnow()
        self.consecutive_failures = 0
        self.updated_at = datetime.utcnow()

    def record_execution_failure(self) -> None:
        """Record failed execution."""
        self.last_execution_at = datetime.utcnow()
        self.consecutive_failures += 1
        self.updated_at = datetime.utcnow()


class CronTrigger(Trigger):
    """Cron-based scheduled trigger."""

    trigger_type: TriggerType = Field(default=TriggerType.CRON, frozen=True)
    cron_expression: str = Field(..., min_length=1)
    timezone: str = Field(default="UTC")
    next_run_time: datetime | None = None

    @field_validator("cron_expression")
    @classmethod
    def validate_cron_expression(cls, v: str) -> str:
        """Basic validation of cron expression format."""
        if not v.strip():
            raise ValueError("Cron expression cannot be empty")

        # Basic format check - should have 5 or 6 parts
        parts = v.strip().split()
        if len(parts) not in [5, 6]:
            raise ValueError("Cron expression must have 5 or 6 parts")

        return v.strip()

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        """Validate timezone string."""
        if not v.strip():
            raise ValueError("Timezone cannot be empty")
        return v.strip()


class WebhookTrigger(Trigger):
    """Webhook-based event trigger."""

    trigger_type: TriggerType = Field(default=TriggerType.WEBHOOK, frozen=True)
    webhook_id: str = Field(..., min_length=1)
    allowed_methods: list[str] = Field(default_factory=lambda: ["POST"])
    webhook_type: WebhookType = Field(default=WebhookType.GENERIC)
    validation_rules: dict[str, Any] = Field(default_factory=dict)

    # Generic webhook configuration - supports any webhook type
    webhook_config: dict[str, Any] | None = None

    @field_validator("webhook_id")
    @classmethod
    def validate_webhook_id(cls, v: str) -> str:
        """Validate webhook ID."""
        if not v.strip():
            raise ValueError("Webhook ID cannot be empty")
        return v.strip()

    @field_validator("allowed_methods")
    @classmethod
    def validate_allowed_methods(cls, v: list[str]) -> list[str]:
        """Validate HTTP methods."""
        if not v:
            raise ValueError("At least one HTTP method must be allowed")

        valid_methods = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
        for method in v:
            if method.upper() not in valid_methods:
                raise ValueError(f"Invalid HTTP method: {method}")

        return [method.upper() for method in v]


class TriggerExecution(BaseModel):
    """Record of a trigger execution."""

    id: UUID = Field(default_factory=uuid4)
    trigger_id: UUID
    executed_at: datetime = Field(default_factory=datetime.utcnow)
    status: ExecutionStatus
    task_id: UUID | None = None
    execution_time_ms: int = Field(ge=0)
    error_message: str | None = None
    trigger_data: dict[str, Any] = Field(default_factory=dict)
    workflow_id: str | None = None  # Temporal workflow ID
    run_id: str | None = None  # Temporal run ID

    class Config:
        """Pydantic model configuration."""

        from_attributes = True

    @field_validator("execution_time_ms")
    @classmethod
    def validate_execution_time(cls, v: int) -> int:
        """Validate execution time is non-negative."""
        if v < 0:
            raise ValueError("Execution time cannot be negative")
        return v

    def is_successful(self) -> bool:
        """Check if execution was successful."""
        return self.status == ExecutionStatus.SUCCESS

    def has_error(self) -> bool:
        """Check if execution had an error."""
        return self.status in [ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT]


class TriggerCreate(BaseModel):
    """Model for creating a new trigger."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=1000)
    agent_id: UUID
    trigger_type: TriggerType
    task_parameters: dict[str, Any] = Field(default_factory=dict)
    conditions: dict[str, Any] = Field(default_factory=dict)
    created_by: str
    workspace_id: str | None = None

    # Business logic safety
    failure_threshold: int = Field(default=5, ge=1, le=100)

    # Cron-specific fields
    cron_expression: str | None = None
    timezone: str = Field(default="UTC")

    # Webhook-specific fields
    webhook_id: str | None = None
    allowed_methods: list[str] = Field(default_factory=lambda: ["POST"])
    webhook_type: WebhookType = Field(default=WebhookType.GENERIC)
    validation_rules: dict[str, Any] = Field(default_factory=dict)
    webhook_config: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_trigger_type_fields(self) -> "TriggerCreate":
        """Validate that required fields are present for each trigger type."""
        if self.trigger_type == TriggerType.CRON:
            if not self.cron_expression:
                raise ValueError("cron_expression is required for CRON triggers")
        elif self.trigger_type == TriggerType.WEBHOOK:
            if not self.webhook_id:
                raise ValueError("webhook_id is required for WEBHOOK triggers")

        return self


class TriggerUpdate(BaseModel):
    """Model for updating an existing trigger."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    is_active: bool | None = None
    task_parameters: dict[str, Any] | None = None
    conditions: dict[str, Any] | None = None

    # Business logic safety
    failure_threshold: int | None = Field(None, ge=1, le=100)

    # Cron-specific fields
    cron_expression: str | None = None
    timezone: str | None = None

    # Webhook-specific fields
    allowed_methods: list[str] | None = None
    webhook_type: WebhookType | None = None
    validation_rules: dict[str, Any] | None = None
    webhook_config: dict[str, Any] | None = None
