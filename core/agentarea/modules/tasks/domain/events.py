from datetime import datetime
from typing import Any, Dict
from uuid import UUID

from agentarea.common.events.base_events import DomainEvent
from agentarea.common.utils.types import TaskState, TaskStatus, Artifact


class TaskCreated(DomainEvent):
    """Event emitted when a new task is created"""

    def __init__(
        self,
        task_id: str,
        agent_id: UUID,
        description: str | None = None,
        parameters: Dict[str, Any] | None = None,
        session_id: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        # Store attributes on self for backward compatibility
        self.task_id = task_id
        self.agent_id = agent_id
        self.description = description
        self.parameters = parameters or {}
        self.session_id = session_id
        self.metadata = metadata or {}

        # Initialize parent with data populated properly
        super().__init__(
            task_id=task_id,
            agent_id=str(agent_id),  # Convert UUID to string for JSON serialization
            description=description,
            parameters=self.parameters,
            session_id=session_id,
            metadata=self.metadata,
        )


class TaskUpdated(DomainEvent):
    """Event emitted when a task is updated"""

    def __init__(
        self,
        task_id: str,
        status: TaskStatus,
        artifacts: list[Artifact] | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self.task_id = task_id
        self.status = status
        self.artifacts = artifacts or []
        self.metadata = metadata or {}


class TaskStatusChanged(DomainEvent):
    """Event emitted when a task status changes"""

    def __init__(
        self,
        task_id: str,
        old_status: TaskState,
        new_status: TaskState,
        message: str | None = None,
        status_timestamp: datetime | None = None,
    ) -> None:
        super().__init__()
        self.task_id = task_id
        self.old_status = old_status
        self.new_status = new_status
        self.message = message
        self.status_timestamp = status_timestamp or datetime.utcnow()


class TaskCompleted(DomainEvent):
    """Event emitted when a task is completed successfully"""

    def __init__(
        self,
        task_id: str,
        result: Dict[str, Any] | None = None,
        artifacts: list[Artifact] | None = None,
        execution_time: float | None = None,
    ) -> None:
        super().__init__()
        self.task_id = task_id
        self.result = result or {}
        self.artifacts = artifacts or []
        self.execution_time = execution_time


class TaskFailed(DomainEvent):
    """Event emitted when a task fails"""

    def __init__(
        self,
        task_id: str,
        error_message: str,
        error_code: str | None = None,
        stack_trace: str | None = None,
    ) -> None:
        super().__init__()
        self.task_id = task_id
        self.error_message = error_message
        self.error_code = error_code
        self.stack_trace = stack_trace


class TaskCanceled(DomainEvent):
    """Event emitted when a task is canceled"""

    def __init__(
        self, task_id: str, reason: str | None = None, canceled_by: str | None = None
    ) -> None:
        super().__init__()
        self.task_id = task_id
        self.reason = reason
        self.canceled_by = canceled_by


class TaskInputRequired(DomainEvent):
    """Event emitted when a task requires user input"""

    def __init__(
        self,
        task_id: str,
        input_request: str,
        input_schema: Dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> None:
        super().__init__()
        self.task_id = task_id
        self.input_request = input_request
        self.input_schema = input_schema or {}
        self.timeout = timeout


class TaskArtifactAdded(DomainEvent):
    """Event emitted when an artifact is added to a task"""

    def __init__(self, task_id: str, artifact: Artifact, artifact_type: str | None = None) -> None:
        super().__init__()
        self.task_id = task_id
        self.artifact = artifact
        self.artifact_type = artifact_type


class TaskAssigned(DomainEvent):
    """Event emitted when a task is assigned to an agent"""

    def __init__(
        self,
        task_id: str,
        agent_id: UUID,
        assigned_by: str | None = None,
        assignment_reason: str | None = None,
    ) -> None:
        super().__init__()
        self.task_id = task_id
        self.agent_id = agent_id
        self.assigned_by = assigned_by
        self.assignment_reason = assignment_reason
