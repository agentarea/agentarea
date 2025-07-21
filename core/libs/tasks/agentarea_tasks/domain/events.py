from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from agentarea_common.events.base_events import DomainEvent
from agentarea_common.utils.types import Artifact, TaskState, TaskStatus


@dataclass
class TaskCreated(DomainEvent):
    """Event emitted when a new task is created."""

    task_id: str
    agent_id: str
    description: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskUpdated(DomainEvent):
    """Event emitted when a task is updated."""

    task_id: str
    status: TaskStatus
    artifacts: list[Artifact] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskStatusChanged(DomainEvent):
    """Event emitted when a task status changes."""

    task_id: str
    old_status: TaskState
    new_status: TaskState
    message: str | None = None
    status_timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class TaskCompleted(DomainEvent):
    """Event emitted when a task is completed successfully."""

    task_id: str
    result: dict[str, Any] = field(default_factory=dict)
    artifacts: list[Artifact] = field(default_factory=list)
    execution_time: float | None = None


@dataclass
class TaskFailed(DomainEvent):
    """Event emitted when a task fails."""

    task_id: str
    error_message: str
    error_code: str | None = None
    stack_trace: str | None = None


@dataclass
class TaskCanceled(DomainEvent):
    """Event emitted when a task is canceled."""

    task_id: str
    reason: str | None = None
    canceled_by: str | None = None


@dataclass
class TaskInputRequired(DomainEvent):
    """Event emitted when a task requires user input."""

    task_id: str
    input_request: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    timeout: int | None = None


@dataclass
class TaskArtifactAdded(DomainEvent):
    """Event emitted when an artifact is added to a task."""

    task_id: str
    artifact: Artifact
    artifact_type: str | None = None


@dataclass
class TaskAssigned(DomainEvent):
    """Event emitted when a task is assigned to an agent."""

    task_id: str
    agent_id: UUID
    assigned_by: str | None = None
    assignment_reason: str | None = None
