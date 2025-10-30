"""Abstract base task service providing common functionality.

This module defines the BaseTaskService abstract class that provides common
CRUD operations and validation methods for all task service implementations.
It addresses Requirements 1.1, 1.2, 2.1, and 2.2 by establishing a clean
hierarchy and eliminating code duplication.
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from agentarea_common.events.broker import EventBroker

from .events import TaskStatusChanged, TaskUpdated
from .models import SimpleTask, Task

logger = logging.getLogger(__name__)


class TaskValidationError(Exception):
    """Raised when task validation fails."""

    pass


class TaskNotFoundError(Exception):
    """Raised when a task is not found."""

    pass


class BaseTaskService(ABC):
    """Abstract base class for all task services providing common functionality.

    This class implements common CRUD operations and validation methods that
    are shared across all task service implementations. It ensures consistent
    behavior and eliminates code duplication (Requirements 1.1, 2.1, 2.2).

    Subclasses must implement the abstract submit_task method to define
    their specific execution behavior (Requirement 1.2).
    """

    def __init__(self, task_repository, event_broker: EventBroker):
        """Initialize with repository and event broker.

        Args:
            task_repository: Repository for task persistence
            event_broker: Event broker for publishing domain events
        """
        self.task_repository = task_repository
        self.event_broker = event_broker

    async def create_task(self, task: SimpleTask) -> SimpleTask:
        """Create a new task with validation and event publishing.

        Args:
            task: The task to create

        Returns:
            The created task with updated timestamps

        Raises:
            TaskValidationError: If task validation fails
        """
        # Validate the task before creation
        await self._validate_task(task)

        # Ensure timestamps are set
        if not task.created_at:
            task.created_at = datetime.utcnow()
        if not task.updated_at:
            task.updated_at = task.created_at

        # Convert SimpleTask to Task domain model for repository

        task_domain = Task(
            id=task.id,
            agent_id=task.agent_id,
            description=task.description,
            parameters=task.task_parameters,
            status=task.status,
            result=task.result,
            error=task.error_message,
            created_at=task.created_at,
            updated_at=task.updated_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            execution_id=task.execution_id,
            # user_id and workspace_id will be set automatically by WorkspaceScopedRepository
            metadata=task.metadata,
        )

        # Persist the task
        created_task_domain = await self.task_repository.create_task(task_domain)

        # Convert back to SimpleTask for return
        created_task = SimpleTask(
            id=created_task_domain.id,
            title=task.title,  # Preserve original title
            description=created_task_domain.description,
            query=task.query,  # Preserve original query
            user_id=created_task_domain.user_id,
            agent_id=created_task_domain.agent_id,
            status=created_task_domain.status,
            task_parameters=created_task_domain.parameters,
            result=created_task_domain.result,
            error_message=created_task_domain.error,
            created_at=created_task_domain.created_at,
            updated_at=created_task_domain.updated_at,
            started_at=created_task_domain.started_at,
            completed_at=created_task_domain.completed_at,
            execution_id=created_task_domain.execution_id,
            workspace_id=created_task_domain.workspace_id,
            metadata=created_task_domain.metadata,
        )

        # Publish creation event - temporarily disabled due to event creation issue
        try:
            # await self._publish_task_event(
            #     TaskCreated(
            #         task_id=str(created_task.id),
            #         agent_id=str(created_task.agent_id),
            #         description=created_task.description,
            #         parameters=created_task.task_parameters,
            #         metadata=created_task.metadata,
            #     )
            # )
            pass  # Temporarily disabled
        except Exception as e:
            # Log the error but don't fail the operation
            logger.error(f"Failed to publish TaskCreated event: {e}")

        logger.info(f"Created task {created_task.id} for agent {created_task.agent_id}")
        return created_task

    async def get_task(self, task_id: UUID) -> SimpleTask | None:
        """Get a task by ID.

        Args:
            task_id: The unique identifier of the task

        Returns:
            The task if found, None otherwise
        """
        task_domain = await self.task_repository.get_task(task_id)
        if not task_domain:
            return None

        return self._task_to_simple_task(task_domain)

    async def update_task(self, task: SimpleTask) -> SimpleTask:
        """Update an existing task with validation and event publishing.

        Args:
            task: The task to update

        Returns:
            The updated task

        Raises:
            TaskValidationError: If task validation fails
            TaskNotFoundError: If task doesn't exist
        """
        # Validate the task before update
        await self._validate_task(task)

        # Check if task exists
        existing_task = await self.get_task(task.id)
        if not existing_task:
            raise TaskNotFoundError(f"Task {task.id} not found")

        # Update timestamp
        task.updated_at = datetime.utcnow()

        # Check for status change
        old_status = existing_task.status
        new_status = task.status

        # Convert SimpleTask to Task domain model for repository
        from .models import Task

        task_domain = Task(
            id=task.id,
            agent_id=task.agent_id,
            description=task.description,
            parameters=task.task_parameters,
            status=task.status,
            result=task.result,
            error=task.error_message,
            created_at=task.created_at,
            updated_at=task.updated_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            execution_id=task.execution_id,
            user_id=task.user_id,
            workspace_id=task.workspace_id,
            metadata=task.metadata,
        )

        # Persist the update
        updated_task_domain = await self.task_repository.update_task(task_domain)

        # Convert back to SimpleTask for return
        updated_task = SimpleTask(
            id=updated_task_domain.id,
            title=task.title,  # Preserve original title
            description=updated_task_domain.description,
            query=task.query,  # Preserve original query
            user_id=updated_task_domain.user_id,
            agent_id=updated_task_domain.agent_id,
            status=updated_task_domain.status,
            task_parameters=updated_task_domain.parameters,
            result=updated_task_domain.result,
            error_message=updated_task_domain.error,
            created_at=updated_task_domain.created_at,
            updated_at=updated_task_domain.updated_at,
            started_at=updated_task_domain.started_at,
            completed_at=updated_task_domain.completed_at,
            execution_id=updated_task_domain.execution_id,
            workspace_id=updated_task_domain.workspace_id,
            metadata=updated_task_domain.metadata,
        )

        # Publish update event
        try:
            await self._publish_task_event(
                TaskUpdated(
                    task_id=str(updated_task.id),
                    status=updated_task.status,
                    metadata=updated_task.metadata,
                )
            )

            # Publish status change event if status changed
            if old_status != new_status:
                await self._publish_task_event(
                    TaskStatusChanged(
                        task_id=str(updated_task.id),
                        old_status=old_status,
                        new_status=new_status,
                        status_timestamp=updated_task.updated_at,
                    )
                )
        except Exception as e:
            # Log the error but don't fail the operation
            logger.error(f"Failed to publish task update events: {e}")

        logger.info(f"Updated task {updated_task.id}")
        return updated_task

    async def list_tasks(
        self,
        agent_id: UUID | None = None,
        user_id: str | None = None,
        workspace_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SimpleTask]:
        """List tasks with optional filtering.

        Args:
            agent_id: Filter by agent ID
            user_id: Filter by user ID
            workspace_id: Filter by workspace ID
            status: Filter by task status
            limit: Maximum number of tasks to return
            offset: Number of tasks to skip

        Returns:
            List of tasks matching the criteria
        """
        if workspace_id and user_id:
            tasks = await self.task_repository.list_tasks(
                creator_scoped=True, limit=limit, offset=offset
            )
        elif workspace_id:
            tasks = await self.task_repository.list_tasks(limit=limit, offset=offset)
        elif agent_id:
            tasks = await self.task_repository.get_by_agent_id(agent_id, limit, offset)
        elif user_id:
            tasks = await self.task_repository.list_tasks(
                creator_scoped=True, limit=limit, offset=offset
            )
        elif status:
            tasks = await self.task_repository.get_by_status(status)
        else:
            tasks = await self.task_repository.list_tasks()

        # Convert Task domain models to SimpleTask
        return [self._task_to_simple_task(task) for task in tasks]

    async def delete_task(self, task_id: UUID) -> bool:
        """Delete a task by ID.

        Args:
            task_id: The unique identifier of the task to delete

        Returns:
            True if the task was successfully deleted, False if not found
        """
        # Check if task exists before deletion
        existing_task = await self.get_task(task_id)
        if not existing_task:
            return False

        # Delete the task
        success = await self.task_repository.delete_task(task_id)

        if success:
            logger.info(f"Deleted task {task_id}")

        return success

    # Protected methods for subclasses

    def _task_to_simple_task(self, task: Task) -> SimpleTask:
        """Convert Task domain model to SimpleTask.

        Args:
            task: Task domain model from repository

        Returns:
            SimpleTask model for service/API layer
        """
        return SimpleTask(
            id=task.id,
            title=task.description,  # Use description as title
            description=task.description,
            query=task.description,  # Use description as query
            user_id=task.user_id or "",
            agent_id=task.agent_id,
            status=task.status,
            task_parameters=task.parameters,  # Convert parameters -> task_parameters
            result=task.result,
            error_message=task.error,
            created_at=task.created_at,
            updated_at=task.updated_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            execution_id=task.execution_id,
            workspace_id=task.workspace_id,
            metadata=task.metadata,
        )

    async def _validate_task(self, task: SimpleTask) -> None:
        """Validate a task before creation or update.

        This method performs common validation that applies to all task types.
        Subclasses can override this method to add additional validation.

        Args:
            task: The task to validate

        Raises:
            TaskValidationError: If validation fails
        """
        if not task.title or not task.title.strip():
            raise TaskValidationError("Task title is required")

        if not task.description or not task.description.strip():
            raise TaskValidationError("Task description is required")

        if not task.query or not task.query.strip():
            raise TaskValidationError("Task query is required")

        if not task.user_id or not task.user_id.strip():
            raise TaskValidationError("Task user_id is required")

        if not task.agent_id:
            raise TaskValidationError("Task agent_id is required")

        # Validate status is one of the allowed values
        valid_statuses = {
            "submitted",
            "pending",
            "running",
            "working",
            "completed",
            "failed",
            "cancelled",
        }
        if task.status not in valid_statuses:
            raise TaskValidationError(f"Invalid task status: {task.status}")

        # Validate datetime field relationships
        try:
            task._validate_datetime_fields()
        except ValueError as e:
            raise TaskValidationError(str(e)) from e

    async def _publish_task_event(self, event) -> None:
        """Publish a task-related domain event.

        This method handles event publishing with error handling to ensure
        that event publishing failures don't break the main task operations.

        Args:
            event: The domain event to publish
        """
        try:
            await self.event_broker.publish(event)
        except Exception as e:
            # Log the error but don't fail the operation
            logger.error(f"Failed to publish event {event.__class__.__name__}: {e}")

    # Abstract methods that subclasses must implement

    @abstractmethod
    async def submit_task(self, task: SimpleTask) -> SimpleTask:
        """Submit a task for execution.

        This method must be implemented by subclasses to define their specific
        task submission and execution behavior.

        Args:
            task: The task to submit for execution

        Returns:
            The submitted task with updated status

        Raises:
            NotImplementedError: If not implemented by subclass
        """
        raise NotImplementedError("Subclasses must implement submit_task method")
