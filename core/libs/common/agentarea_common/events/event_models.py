"""Comprehensive Pydantic event models for the AgentArea system.

This module provides unified event models that replace scattered event definitions
across the codebase. It establishes a type-safe event system that integrates with
our EventEnvelope and EventBroker infrastructure.
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_serializer

from .base_events import EventEnvelope


class EventType(str, Enum):
    """Unified event types for the AgentArea system."""

    # Task lifecycle events
    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"
    TASK_PAUSED = "task.paused"
    TASK_RESUMED = "task.resumed"

    # Workflow execution events
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"
    WORKFLOW_PAUSED = "workflow.paused"
    WORKFLOW_RESUMED = "workflow.resumed"
    WORKFLOW_CANCELLED = "workflow.cancelled"

    # LLM execution events
    LLM_CALL_STARTED = "workflow.LLMCallStarted"
    LLM_CALL_COMPLETED = "workflow.LLMCallCompleted"
    LLM_CALL_FAILED = "workflow.LLMCallFailed"
    LLM_CALL_CHUNK = "workflow.LLMCallChunk"

    # Tool execution events
    TOOL_EXECUTION_STARTED = "workflow.ToolExecutionStarted"
    TOOL_EXECUTION_COMPLETED = "workflow.ToolExecutionCompleted"
    TOOL_EXECUTION_FAILED = "workflow.ToolExecutionFailed"

    # Agent communication events
    AGENT_MESSAGE_SENT = "workflow.AgentMessageSent"
    AGENT_MESSAGE_RECEIVED = "workflow.AgentMessageReceived"
    AGENT_COMMUNICATION_FAILED = "workflow.AgentCommunicationFailed"

    # MCP server events
    MCP_SERVER_CREATE_REQUESTED = "mcp.server.create.requested"
    MCP_SERVER_CREATING = "mcp.server.creating"
    MCP_SERVER_CREATED = "mcp.server.created"
    MCP_SERVER_READY = "mcp.server.ready"
    MCP_SERVER_FAILED = "mcp.server.failed"
    MCP_SERVER_STOPPING = "mcp.server.stopping"
    MCP_SERVER_STOPPED = "mcp.server.stopped"
    MCP_SERVER_DELETED = "mcp.server.deleted"
    MCP_SERVER_HEALTH_CHECK = "mcp.server.health.check"
    MCP_SERVER_UNHEALTHY = "mcp.server.unhealthy"
    MCP_SERVER_RECOVERED = "mcp.server.recovered"

    # System and heartbeat events
    HEARTBEAT = "heartbeat"
    SYSTEM_ERROR = "system.error"


class BaseEvent(BaseModel):
    """Base event model compatible with EventEnvelope."""

    event_id: UUID = Field(default_factory=uuid4, description="Unique event identifier")
    event_type: EventType = Field(..., description="Type of the event")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Event timestamp (UTC)"
    )
    aggregate_id: str = Field(..., description="ID of the aggregate this event relates to")
    aggregate_type: str = Field(
        ..., description="Type of the aggregate (task, workflow, mcp_server)"
    )
    correlation_id: str | None = Field(None, description="Request correlation ID for tracing")

    @field_serializer("timestamp")
    def serialize_timestamp(self, value: datetime, _info):
        return value.isoformat()

    def to_envelope(self) -> EventEnvelope:
        """Convert to EventEnvelope format for broker compatibility."""
        return EventEnvelope(
            event_id=self.event_id,
            event_type=self.event_type.value,
            timestamp=self.timestamp,
            data=self.model_dump(exclude={"event_id", "timestamp", "event_type"}),
        )


# --- Task Events ---


class TaskEvent(BaseEvent):
    """Base class for task-related events."""

    aggregate_type: Literal["task"] = "task"
    task_id: UUID = Field(..., description="Task identifier")
    user_id: str | None = Field(None, description="User who owns the task")
    agent_id: UUID | None = Field(None, description="Agent executing the task")


class TaskCreatedEvent(TaskEvent):
    """Event emitted when a task is created."""

    event_type: Literal[EventType.TASK_CREATED] = EventType.TASK_CREATED
    title: str = Field(..., description="Task title")
    description: str = Field(..., description="Task description")
    query: str = Field(..., description="Task query/prompt")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Task parameters")


class TaskUpdatedEvent(TaskEvent):
    """Event emitted when a task is updated."""

    event_type: Literal[EventType.TASK_UPDATED] = EventType.TASK_UPDATED
    changes: dict[str, Any] = Field(..., description="Fields that were changed")
    previous_status: str | None = Field(None, description="Previous task status")
    current_status: str = Field(..., description="Current task status")


class TaskStartedEvent(TaskEvent):
    """Event emitted when task execution starts."""

    event_type: Literal[EventType.TASK_STARTED] = EventType.TASK_STARTED
    execution_id: str = Field(..., description="Workflow execution ID")


class TaskCompletedEvent(TaskEvent):
    """Event emitted when a task completes successfully."""

    event_type: Literal[EventType.TASK_COMPLETED] = EventType.TASK_COMPLETED
    execution_id: str = Field(..., description="Workflow execution ID")
    result: dict[str, Any] = Field(..., description="Task execution result")
    execution_time_seconds: float | None = Field(None, description="Task execution duration")


class TaskFailedEvent(TaskEvent):
    """Event emitted when a task fails."""

    event_type: Literal[EventType.TASK_FAILED] = EventType.TASK_FAILED
    execution_id: str | None = Field(None, description="Workflow execution ID")
    error_message: str = Field(..., description="Error message")
    error_type: str = Field(..., description="Error type/class name")
    is_retryable: bool = Field(default=False, description="Whether the error is retryable")
    retry_count: int = Field(default=0, description="Number of retry attempts")


class TaskCancelledEvent(TaskEvent):
    """Event emitted when a task is cancelled."""

    event_type: Literal[EventType.TASK_CANCELLED] = EventType.TASK_CANCELLED
    execution_id: str | None = Field(None, description="Workflow execution ID")
    cancelled_by: str = Field(..., description="User who cancelled the task")
    reason: str | None = Field(None, description="Cancellation reason")


# --- Workflow Events ---


class WorkflowEvent(BaseEvent):
    """Base class for workflow execution events."""

    aggregate_type: Literal["workflow"] = "workflow"
    task_id: UUID = Field(..., description="Associated task ID")
    execution_id: str = Field(..., description="Workflow execution ID")
    agent_id: UUID = Field(..., description="Agent executing the workflow")
    iteration: int = Field(default=1, description="Workflow iteration number")


class LLMCallStartedEvent(WorkflowEvent):
    """Event emitted when an LLM call starts."""

    event_type: Literal[EventType.LLM_CALL_STARTED] = EventType.LLM_CALL_STARTED
    model_id: str = Field(..., description="LLM model identifier")
    provider_type: str | None = Field(None, description="LLM provider type")
    message_count: int = Field(..., description="Number of messages in the call")
    prompt_tokens: int | None = Field(None, description="Number of prompt tokens")


class LLMCallCompletedEvent(WorkflowEvent):
    """Event emitted when an LLM call completes successfully."""

    event_type: Literal[EventType.LLM_CALL_COMPLETED] = EventType.LLM_CALL_COMPLETED
    model_id: str = Field(..., description="LLM model identifier")
    provider_type: str | None = Field(None, description="LLM provider type")
    response_text: str = Field(..., description="LLM response text")
    prompt_tokens: int | None = Field(None, description="Number of prompt tokens")
    completion_tokens: int | None = Field(None, description="Number of completion tokens")
    total_tokens: int | None = Field(None, description="Total tokens used")
    response_time_ms: int | None = Field(None, description="Response time in milliseconds")


class LLMCallFailedEvent(WorkflowEvent):
    """Event emitted when an LLM call fails."""

    event_type: Literal[EventType.LLM_CALL_FAILED] = EventType.LLM_CALL_FAILED
    model_id: str = Field(..., description="LLM model identifier")
    provider_type: str | None = Field(None, description="LLM provider type")
    error: str = Field(..., description="Error message")
    error_type: str = Field(..., description="Error type/class name")
    is_auth_error: bool = Field(default=False, description="Authentication error flag")
    is_rate_limit_error: bool = Field(default=False, description="Rate limit error flag")
    is_quota_error: bool = Field(default=False, description="Quota error flag")
    is_model_error: bool = Field(default=False, description="Model error flag")
    is_network_error: bool = Field(default=False, description="Network error flag")
    retryable: bool = Field(default=False, description="Whether the error is retryable")
    retry_after: int | None = Field(None, description="Retry after seconds for rate limits")
    quota_type: str | None = Field(None, description="Type of quota exceeded")
    status_code: int | None = Field(None, description="HTTP status code for network errors")


class LLMCallChunkEvent(WorkflowEvent):
    """Event emitted for streaming LLM response chunks."""

    event_type: Literal[EventType.LLM_CALL_CHUNK] = EventType.LLM_CALL_CHUNK
    chunk: str = Field(..., description="Response chunk content")
    chunk_index: int = Field(..., description="Chunk sequence number")
    is_final: bool = Field(default=False, description="Whether this is the final chunk")


class ToolExecutionStartedEvent(WorkflowEvent):
    """Event emitted when tool execution starts."""

    event_type: Literal[EventType.TOOL_EXECUTION_STARTED] = EventType.TOOL_EXECUTION_STARTED
    tool_name: str = Field(..., description="Name of the tool being executed")
    arguments: dict[str, Any] = Field(..., description="Tool execution arguments")


class ToolExecutionCompletedEvent(WorkflowEvent):
    """Event emitted when tool execution completes."""

    event_type: Literal[EventType.TOOL_EXECUTION_COMPLETED] = EventType.TOOL_EXECUTION_COMPLETED
    tool_name: str = Field(..., description="Name of the executed tool")
    arguments: dict[str, Any] = Field(..., description="Tool execution arguments")
    result: dict[str, Any] = Field(..., description="Tool execution result")
    execution_time_ms: int | None = Field(None, description="Execution time in milliseconds")


class ToolExecutionFailedEvent(WorkflowEvent):
    """Event emitted when tool execution fails."""

    event_type: Literal[EventType.TOOL_EXECUTION_FAILED] = EventType.TOOL_EXECUTION_FAILED
    tool_name: str = Field(..., description="Name of the failed tool")
    arguments: dict[str, Any] = Field(..., description="Tool execution arguments")
    error: str = Field(..., description="Error message")
    error_type: str = Field(..., description="Error type/class name")
    is_retryable: bool = Field(default=False, description="Whether the error is retryable")


class AgentMessageSentEvent(WorkflowEvent):
    """Event emitted when an agent sends a message."""

    event_type: Literal[EventType.AGENT_MESSAGE_SENT] = EventType.AGENT_MESSAGE_SENT
    target_agent_id: UUID = Field(..., description="Target agent ID")
    message_content: str = Field(..., description="Message content")
    message_type: str = Field(default="text", description="Message type")


class AgentMessageReceivedEvent(WorkflowEvent):
    """Event emitted when an agent receives a message."""

    event_type: Literal[EventType.AGENT_MESSAGE_RECEIVED] = EventType.AGENT_MESSAGE_RECEIVED
    source_agent_id: UUID = Field(..., description="Source agent ID")
    message_content: str = Field(..., description="Message content")
    message_type: str = Field(default="text", description="Message type")


# --- MCP Events ---


class MCPEvent(BaseEvent):
    """Base class for MCP server events."""

    aggregate_type: Literal["mcp_server"] = "mcp_server"
    config_id: UUID = Field(..., description="MCP server configuration ID")
    agent_id: UUID | None = Field(None, description="Associated agent ID")


class MCPServerCreateRequestedEvent(MCPEvent):
    """Event emitted when MCP server creation is requested."""

    event_type: Literal[EventType.MCP_SERVER_CREATE_REQUESTED] = (
        EventType.MCP_SERVER_CREATE_REQUESTED
    )
    template: str = Field(..., description="MCP server template name")
    environment: dict[str, Any] = Field(default_factory=dict, description="Environment variables")
    replicas: int = Field(default=1, description="Number of replicas")
    user_id: UUID = Field(..., description="User who requested the server")


class MCPServerReadyEvent(MCPEvent):
    """Event emitted when MCP server is ready."""

    event_type: Literal[EventType.MCP_SERVER_READY] = EventType.MCP_SERVER_READY
    runtime_id: str = Field(..., description="Container/Pod runtime ID")
    endpoint: str = Field(..., description="Public endpoint URL")
    internal_endpoint: str = Field(..., description="Internal service endpoint")
    health_check_url: str = Field(..., description="Health check endpoint")


class MCPServerFailedEvent(MCPEvent):
    """Event emitted when MCP server deployment fails."""

    event_type: Literal[EventType.MCP_SERVER_FAILED] = EventType.MCP_SERVER_FAILED
    error: str = Field(..., description="Error message")
    error_code: str = Field(..., description="Error code")
    runtime_id: str | None = Field(None, description="Container/Pod runtime ID if available")
    retry_count: int = Field(default=0, description="Number of retry attempts")


# --- System Events ---


class HeartbeatEvent(BaseEvent):
    """Heartbeat event for keeping connections alive."""

    event_type: Literal[EventType.HEARTBEAT] = EventType.HEARTBEAT
    aggregate_type: Literal["system"] = "system"
    service_name: str = Field(..., description="Service sending the heartbeat")
    health_status: str = Field(default="healthy", description="Service health status")


class SystemErrorEvent(BaseEvent):
    """System-level error event."""

    event_type: Literal[EventType.SYSTEM_ERROR] = EventType.SYSTEM_ERROR
    aggregate_type: Literal["system"] = "system"
    service_name: str = Field(..., description="Service that encountered the error")
    error_message: str = Field(..., description="Error message")
    error_type: str = Field(..., description="Error type/class name")
    stack_trace: str | None = Field(None, description="Stack trace if available")
    severity: str = Field(default="error", description="Error severity level")


# Union type for all events
DomainEventModel = (
    TaskCreatedEvent
    | TaskUpdatedEvent
    | TaskStartedEvent
    | TaskCompletedEvent
    | TaskFailedEvent
    | TaskCancelledEvent
    | LLMCallStartedEvent
    | LLMCallCompletedEvent
    | LLMCallFailedEvent
    | LLMCallChunkEvent
    | ToolExecutionStartedEvent
    | ToolExecutionCompletedEvent
    | ToolExecutionFailedEvent
    | AgentMessageSentEvent
    | AgentMessageReceivedEvent
    | MCPServerCreateRequestedEvent
    | MCPServerReadyEvent
    | MCPServerFailedEvent
    | HeartbeatEvent
    | SystemErrorEvent
)


# Utility functions for backward compatibility


def create_task_event_envelope(
    event_type: str,
    task_id: UUID,
    data: dict[str, Any],
    user_id: str | None = None,
    agent_id: UUID | None = None,
) -> EventEnvelope:
    """Create a task event envelope for backward compatibility."""
    return EventEnvelope(
        event_id=uuid4(),
        timestamp=datetime.now(UTC),
        event_type=event_type,
        data={
            "aggregate_id": str(task_id),
            "aggregate_type": "task",
            "task_id": str(task_id),
            "user_id": user_id,
            "agent_id": str(agent_id) if agent_id else None,
            **data,
        },
    )


def create_workflow_event_envelope(
    event_type: str,
    task_id: UUID,
    execution_id: str,
    agent_id: UUID,
    data: dict[str, Any],
    iteration: int = 1,
) -> EventEnvelope:
    """Create a workflow event envelope for backward compatibility."""
    return EventEnvelope(
        event_id=uuid4(),
        timestamp=datetime.now(UTC),
        event_type=event_type,
        data={
            "aggregate_id": str(task_id),
            "aggregate_type": "task",  # Tasks are the primary aggregate for workflows
            "task_id": str(task_id),
            "execution_id": execution_id,
            "agent_id": str(agent_id),
            "iteration": iteration,
            "original_event_type": event_type.replace("workflow.", ""),
            "original_timestamp": datetime.now(UTC).isoformat(),
            "original_data": data,
            **data,
        },
    )
