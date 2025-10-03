"""Event dataclasses for workflow events.

This module provides structured dataclasses for all workflow events
to ensure type safety and consistent data structure across the system.
"""

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class BaseWorkflowEvent(BaseModel):
    """Base class for all workflow events."""

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    task_id: str = ""
    agent_id: str = ""
    execution_id: str = ""
    iteration: int | None = None


class WorkflowStartedEvent(BaseWorkflowEvent):
    """Event emitted when workflow starts."""

    goal_description: str = ""
    max_iterations: int = 0
    budget_limit: float | None = None


class WorkflowCompletedEvent(BaseWorkflowEvent):
    """Event emitted when workflow completes successfully."""

    success: bool = True
    iterations_completed: int = 0
    total_cost: float = 0.0
    final_response: str | None = None


class WorkflowFailedEvent(BaseWorkflowEvent):
    """Event emitted when workflow fails."""

    success: bool = False
    error: str = ""
    error_type: str = ""
    iterations_completed: int = 0
    total_cost: float = 0.0


class IterationStartedEvent(BaseWorkflowEvent):
    """Event emitted when iteration starts."""

    budget_remaining: float = 0.0


class IterationCompletedEvent(BaseWorkflowEvent):
    """Event emitted when iteration completes."""

    total_cost: float = 0.0


class LLMCallStartedEvent(BaseWorkflowEvent):
    """Event emitted when LLM call starts."""

    message_count: int = 0
    model_id: str | None = None


class LLMCallChunkEvent(BaseWorkflowEvent):
    """Event emitted for LLM streaming chunks."""

    chunk: str = ""
    chunk_index: int = 0
    is_final: bool = False
    model_id: str | None = None


class LLMCallCompletedEvent(BaseWorkflowEvent):
    """Event emitted when LLM call completes successfully."""

    content: str = ""
    role: str = "assistant"
    tool_calls: list[dict[str, Any]] | None = None
    usage: dict[str, Any] | None = None
    cost: float = 0.0
    total_cost: float = 0.0
    model_id: str | None = None


class LLMCallFailedEvent(BaseWorkflowEvent):
    """Event emitted when LLM call fails with detailed error information."""

    error: str = ""
    error_type: str = ""
    model_id: str | None = None
    provider_type: str | None = None

    # Authentication errors
    is_auth_error: bool = False

    # Rate limiting errors
    is_rate_limit_error: bool = False
    retry_after: int | None = None

    # Quota/billing errors
    is_quota_error: bool = False
    quota_type: str | None = None  # e.g., "monthly", "daily", "tokens"

    # Model errors
    is_model_error: bool = False
    available_models: list[str] | None = None

    # Network/connection errors
    is_network_error: bool = False
    status_code: int | None = None

    # Additional context
    request_id: str | None = None
    retryable: bool = True


class ToolCallStartedEvent(BaseWorkflowEvent):
    """Event emitted when tool call starts."""

    tool_name: str = ""
    tool_call_id: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallCompletedEvent(BaseWorkflowEvent):
    """Event emitted when tool call completes."""

    tool_name: str = ""
    tool_call_id: str = ""
    success: bool = True
    result: Any = ""
    arguments: dict[str, Any] = Field(default_factory=dict)
    execution_time: str | None = None


class ToolCallFailedEvent(BaseWorkflowEvent):
    """Event emitted when tool call fails."""

    tool_name: str = ""
    tool_call_id: str = ""
    error: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)


class BudgetWarningEvent(BaseWorkflowEvent):
    """Event emitted when budget warning threshold is reached."""

    usage_percentage: float = 0.0
    cost: float = 0.0
    limit: float = 0.0
    message: str = ""


class BudgetExceededEvent(BaseWorkflowEvent):
    """Event emitted when budget is exceeded."""

    cost: float = 0.0
    limit: float = 0.0
    message: str = ""


# Event type mapping for easy conversion from legacy dict format
EVENT_CLASS_MAPPING = {
    "WorkflowStarted": WorkflowStartedEvent,
    "WorkflowCompleted": WorkflowCompletedEvent,
    "WorkflowFailed": WorkflowFailedEvent,
    "IterationStarted": IterationStartedEvent,
    "IterationCompleted": IterationCompletedEvent,
    "LLMCallStarted": LLMCallStartedEvent,
    "LLMCallChunk": LLMCallChunkEvent,
    "LLMCallCompleted": LLMCallCompletedEvent,
    "LLMCallFailed": LLMCallFailedEvent,
    "ToolCallStarted": ToolCallStartedEvent,
    "ToolCallCompleted": ToolCallCompletedEvent,
    "ToolCallFailed": ToolCallFailedEvent,
    "BudgetWarning": BudgetWarningEvent,
    "BudgetExceeded": BudgetExceededEvent,
}


def create_event_from_dict(event_type: str, data: dict[str, Any]) -> BaseWorkflowEvent:
    """Create a structured event from dictionary data."""
    event_class = EVENT_CLASS_MAPPING.get(event_type)
    if not event_class:
        raise ValueError(f"Unknown event type: {event_type}")

    # Filter data to only include fields that exist in the Pydantic model
    class_fields = set(event_class.model_fields.keys())
    filtered_data = {k: v for k, v in data.items() if k in class_fields}

    return event_class(**filtered_data)


def event_to_dict(event: BaseWorkflowEvent) -> dict[str, Any]:
    """Convert structured event back to dictionary format for publishing."""
    event_dict = event.model_dump()

    # Add event type based on class name
    event_type = type(event).__name__.replace("Event", "")

    return {
        "event_type": event_type,
        "event_id": event_dict.pop("event_id"),
        "timestamp": event_dict.pop("timestamp"),
        "data": event_dict,
    }
