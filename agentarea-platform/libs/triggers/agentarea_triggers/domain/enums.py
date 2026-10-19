"""Trigger system enums and value objects."""

from enum import StrEnum


class TriggerType(StrEnum):
    """Types of triggers supported by the system."""

    CRON = "cron"
    STREAM = "stream"


class ConditionType(StrEnum):
    """Kinds of trigger condition; an untyped condition is an LLM condition."""

    LLM = "llm"
    RULE = "rule"
    COMBINED = "combined"


class TriggerStatus(StrEnum):
    """Status of a trigger."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    DISABLED = "disabled"
    FAILED = "failed"
    NEEDS_OWNER = "needs_owner"


class ExecutionStatus(StrEnum):
    """Status of a trigger execution."""

    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    # Turned away by its conditions, or by the trigger being off: no task, and
    # not a failure -- it neither counts toward nor resets failure_threshold.
    SKIPPED = "skipped"
    # Held in an open batch of a windowed trigger until the batch fires.
    BATCHED = "batched"
