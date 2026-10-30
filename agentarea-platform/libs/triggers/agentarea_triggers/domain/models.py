"""Trigger domain models."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from agentarea_common.model_override import check_model_override
from agentarea_common.reasoning_effort import check_reasoning
from agentarea_common.reserved_task_parameters import (
    drop_reserved_parameters,
    reject_reserved_parameters,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from .enums import ExecutionStatus, TriggerType

logger = logging.getLogger(__name__)

# Passed as validation context when rebuilding a trigger from a stored row, so
# the datetime invariants report instead of raising. See validate_datetime_fields.
RECONSTITUTING: dict[str, Any] = {"reconstituting": True}


class ConditionVerdict(BaseModel):
    """What a condition decided about one event, and why."""

    verdict: Literal["met", "not_met"]
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: str = Field(min_length=1)

    @property
    def met(self) -> bool:
        return self.verdict == "met"


class Trigger(BaseModel):
    """Base trigger domain model."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=1000)
    agent_id: UUID
    # The saved task it runs; its text and parameters stand in for the trigger's own.
    task_definition_id: UUID | None = None
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
    needs_new_owner_at: datetime | None = None

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
    def validate_datetime_fields(self, info: ValidationInfo) -> Trigger:
        """Validate datetime field relationships.

        Building a trigger this way out of order is a programming error and
        still raises. Reading one back is different: the three stamps are
        written by different processes, so clock skew alone can invert them,
        and a stored row that trips this would otherwise become permanently
        unreadable -- including through the endpoint you would use to fix it.
        Reconstitution therefore reports the skew and returns the row as it is.
        """
        problems = []
        if self.updated_at < self.created_at:
            problems.append("updated_at cannot be before created_at")
        if self.last_execution_at and self.last_execution_at < self.created_at:
            problems.append("last_execution_at cannot be before created_at")

        if not problems:
            return self

        if (info.context or {}).get("reconstituting"):
            logger.warning(
                "Trigger %s has inconsistent timestamps and was loaded as-is: %s",
                self.id,
                "; ".join(problems),
            )
            return self

        raise ValueError(problems[0])

    def should_disable_due_to_failures(self) -> bool:
        """Check if trigger should be disabled due to consecutive failures."""
        return self.consecutive_failures >= self.failure_threshold

    def record_execution_started(self) -> None:
        """Record that the trigger fired; failures are counted in the database, one at a time."""
        self.last_execution_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()


class CronTrigger(Trigger):
    """Cron-based scheduled trigger."""

    trigger_type: TriggerType = Field(default=TriggerType.CRON, frozen=True)
    cron_expression: str = Field(..., min_length=1)
    timezone: str = Field(default="UTC")

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


class TriggerSession(BaseModel):
    """What happens to the next event of the same session (ADR-0040 §4)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    continue_: bool | None = Field(
        default=None,
        alias="continue",
        description=(
            "The next event with the same session_key joins the same task; null takes "
            "the source type's default (continue when it has sessions)."
        ),
    )
    idle_timeout: str | None = Field(
        default=None,
        pattern=r"^[0-9]+[smhd]$",
        description="How long the task waits for the next event, e.g. '30m'.",
    )


class TriggerBatchWindow(BaseModel):
    """A stream trigger that fires once for the events of a batch (ADR-0040 §4).

    The batch opens with its first event and fires when ``window`` has passed or
    ``max_events`` have joined, whichever comes first. Either may be left out;
    a batch never holds more than the deployment's cap.
    """

    model_config = ConfigDict(extra="forbid")

    window: str | None = Field(
        default=None,
        pattern=r"^[1-9][0-9]*[smhd]$",
        description="How long a batch stays open after its first event, e.g. '1h'.",
    )
    max_events: int | None = Field(
        default=None, ge=2, description="Fire as soon as this many events have joined."
    )

    @model_validator(mode="after")
    def _a_window_or_a_count(self) -> TriggerBatchWindow:
        if self.window is None and self.max_events is None:
            raise ValueError("a batch needs a window or max_events")
        return self

    def window_seconds(self) -> float | None:
        from agentarea_common.config.duration import parse_duration

        return parse_duration(self.window).total_seconds() if self.window else None


class StreamTrigger(Trigger):
    """A trigger on the events of a stream; its subscription holds the stream and filter."""

    trigger_type: TriggerType = Field(default=TriggerType.STREAM, frozen=True)
    session: TriggerSession | None = None
    batch: TriggerBatchWindow | None = None


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
    fired_by: str | None = Field(
        default=None,
        description=(
            "Principal who asked for this one run, when a person did. Empty means "
            "the trigger's own mechanism fired it -- the schedule came due, or an "
            "event arrived. Not the same as created_by, which records whose "
            "context wrote the row and is filled either way."
        ),
    )

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
    task_definition_id: UUID | None = None
    trigger_type: TriggerType
    task_parameters: dict[str, Any] = Field(default_factory=dict)
    conditions: dict[str, Any] = Field(default_factory=dict)
    created_by: str
    workspace_id: str | None = None
    is_active: bool = True

    # Business logic safety
    failure_threshold: int = Field(default=5, ge=1, le=100)

    # Cron-specific fields
    cron_expression: str | None = None
    timezone: str = Field(default="UTC")

    # Stream-specific fields
    stream_id: UUID | None = None
    event_filter: dict[str, Any] | None = None
    session: TriggerSession | None = None
    batch: TriggerBatchWindow | None = None

    _reject_reserved_parameters = field_validator("task_parameters")(reject_reserved_parameters)
    _check_model_override = field_validator("task_parameters")(check_model_override)
    _check_reasoning = field_validator("task_parameters")(check_reasoning)

    @model_validator(mode="after")
    def validate_trigger_type_fields(self) -> TriggerCreate:
        """Validate that required fields are present for each trigger type."""
        if self.trigger_type == TriggerType.CRON:
            if not self.cron_expression:
                raise ValueError("cron_expression is required for CRON triggers")
            if self.batch is not None:
                raise ValueError("only a stream trigger takes a batch")
        elif self.trigger_type == TriggerType.STREAM:
            if not self.stream_id:
                raise ValueError("stream_id is required for STREAM triggers")

        return self


class TriggerUpdate(BaseModel):
    """Model for updating an existing trigger."""

    _drop_reserved_parameters = field_validator("task_parameters")(drop_reserved_parameters)

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    agent_id: UUID | None = None
    task_definition_id: UUID | None = None
    is_active: bool | None = None
    task_parameters: dict[str, Any] | None = None
    conditions: dict[str, Any] | None = None

    # Business logic safety
    failure_threshold: int | None = Field(None, ge=1, le=100)

    # Cron-specific fields
    cron_expression: str | None = None
    timezone: str | None = None

    # Stream-specific fields
    event_filter: dict[str, Any] | None = None
    session: TriggerSession | None = None
    batch: TriggerBatchWindow | None = None


@dataclass(frozen=True)
class TriggerFiring:
    """One firing of a trigger as a subscriber sees it: what happened, and why.

    A dataclass, not a model: ``execution`` is handed back exactly as it was
    recorded, so ``execute_trigger`` returns what it always returned.
    """

    outcome: Literal["reacted", "skipped", "error"]
    reason: str | None = None
    verdict: ConditionVerdict | None = None
    task_id: UUID | None = None
    execution: TriggerExecution | None = None
    # The trigger's own run still going that a scheduled firing gave way to.
    blocked_by: UUID | None = None
