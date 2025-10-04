"""Domain interfaces for task management.

This module defines the core interfaces that separate the domain logic
from implementation details.
"""

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from .models import SimpleTask


class BaseTaskManager(ABC):
    """Abstract base class for task managers.

    This interface defines the core operations that any task manager
    must implement, regardless of the underlying execution engine
    (Temporal, Celery, etc.).
    """

    @abstractmethod
    async def submit_task(self, task: SimpleTask) -> SimpleTask:
        """Submit a task for execution.

        Args:
            task: The task to be executed

        Returns:
            The submitted task with updated status
        """
        pass

    @abstractmethod
    async def get_task(self, task_id: UUID) -> SimpleTask | None:
        """Get a task by its ID.

        Args:
            task_id: The unique identifier of the task

        Returns:
            The task if found, None otherwise
        """
        pass

    @abstractmethod
    async def cancel_task(self, task_id: UUID) -> bool:
        """Cancel a task.

        Args:
            task_id: The unique identifier of the task to cancel

        Returns:
            True if the task was successfully cancelled, False otherwise
        """
        pass

    @abstractmethod
    async def list_tasks(
        self,
        agent_id: UUID | None = None,
        user_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SimpleTask]:
        """List tasks with optional filtering.

        Args:
            agent_id: Filter by agent ID
            user_id: Filter by user ID
            status: Filter by task status
            limit: Maximum number of tasks to return
            offset: Number of tasks to skip

        Returns:
            List of tasks matching the criteria
        """
        pass

    @abstractmethod
    async def get_task_status(self, task_id: UUID) -> str | None:
        """Get the status of a task.

        Args:
            task_id: The unique identifier of the task

        Returns:
            The task status if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_task_result(self, task_id: UUID) -> Any | None:
        """Get the result of a task.

        Args:
            task_id: The unique identifier of the task

        Returns:
            The task result if found, None otherwise
        """
        pass
