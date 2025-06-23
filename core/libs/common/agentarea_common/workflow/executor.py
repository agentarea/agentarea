"""Abstract workflow executor interface.

This provides a clean abstraction over workflow engines like Temporal,
allowing easy replacement of the underlying implementation.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Any
from uuid import UUID


class WorkflowStatus(Enum):
    """Workflow execution status."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TERMINATED = "terminated"
    UNKNOWN = "unknown"


@dataclass
class WorkflowResult:
    """Result of workflow execution."""

    workflow_id: str
    status: WorkflowStatus
    result: dict[str, Any] | None = None
    error: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    execution_time: float | None = None


@dataclass
class WorkflowConfig:
    """Configuration for workflow execution."""

    timeout: timedelta | None = None
    retry_attempts: int = 3
    retry_initial_interval: timedelta = timedelta(seconds=30)
    retry_max_interval: timedelta = timedelta(minutes=10)
    task_queue: str = "default"


class WorkflowExecutor(ABC):
    """Abstract interface for workflow execution engines."""

    @abstractmethod
    async def start_workflow(
        self,
        workflow_name: str,
        workflow_id: str,
        args: dict[str, Any],
        config: WorkflowConfig | None = None,
    ) -> str:
        """Start a workflow execution.

        Args:
            workflow_name: Name/type of workflow to execute
            workflow_id: Unique identifier for this workflow instance
            args: Arguments to pass to the workflow
            config: Optional workflow configuration

        Returns:
            Workflow execution ID (may be same as workflow_id)
        """
        pass

    @abstractmethod
    async def get_workflow_status(self, workflow_id: str) -> WorkflowResult:
        """Get the status of a workflow.

        Args:
            workflow_id: ID of the workflow to check

        Returns:
            Current workflow status and result
        """
        pass

    @abstractmethod
    async def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancel a running workflow.

        Args:
            workflow_id: ID of the workflow to cancel

        Returns:
            True if cancellation was successful
        """
        pass

    @abstractmethod
    async def wait_for_result(
        self, workflow_id: str, timeout: timedelta | None = None
    ) -> WorkflowResult:
        """Wait for workflow completion and return result.

        Args:
            workflow_id: ID of the workflow to wait for
            timeout: Optional timeout for waiting

        Returns:
            Final workflow result

        Raises:
            TimeoutError: If timeout is reached
        """
        pass

    @abstractmethod
    async def signal_workflow(self, workflow_id: str, signal_name: str, data: Any = None) -> None:
        """Send a signal to a running workflow.

        Args:
            workflow_id: ID of the target workflow
            signal_name: Name of the signal to send
            data: Optional data to send with signal
        """
        pass

    @abstractmethod
    async def query_workflow(
        self, workflow_id: str, query_name: str, args: dict[str, Any] | None = None
    ) -> Any:
        """Query a running workflow for data.

        Args:
            workflow_id: ID of the target workflow
            query_name: Name of the query
            args: Optional query arguments

        Returns:
            Query result
        """
        pass


class TaskExecutorInterface(ABC):
    """High-level interface for task execution using workflows.

    This is the main interface that AgentArea services will use,
    providing a simple API for agent task execution.
    """

    @abstractmethod
    async def execute_task_async(
        self,
        task_id: str,
        agent_id: UUID,
        description: str,
        user_id: str | None = None,
        task_parameters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Execute an agent task asynchronously.

        Args:
            task_id: Unique task identifier
            agent_id: UUID of the agent to execute the task
            description: Task description/query
            user_id: User ID requesting the task
            task_parameters: Additional task parameters
            metadata: Task metadata

        Returns:
            Workflow/execution ID for tracking
        """
        pass

    @abstractmethod
    async def get_task_status(self, execution_id: str) -> dict[str, Any]:
        """Get current task execution status.

        Args:
            execution_id: Execution ID returned from execute_task_async

        Returns:
            Task status information
        """
        pass

    @abstractmethod
    async def cancel_task(self, execution_id: str) -> bool:
        """Cancel a running task.

        Args:
            execution_id: Execution ID to cancel

        Returns:
            True if cancellation was successful
        """
        pass

    @abstractmethod
    async def wait_for_task_completion(
        self, execution_id: str, timeout: timedelta | None = None
    ) -> dict[str, Any]:
        """Wait for task completion and return result.

        Args:
            execution_id: Execution ID to wait for
            timeout: Optional timeout

        Returns:
            Task result
        """
        pass
