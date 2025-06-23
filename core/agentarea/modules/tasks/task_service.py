"""Task service for creating and managing tasks with automatic agent execution."""

import logging
from typing import Any
from uuid import UUID

from agentarea.common.events.broker import EventBroker
from agentarea.modules.tasks.domain.events import TaskCreated
from agentarea.modules.tasks.domain.models import Task, TaskPriority, TaskType
from agentarea.modules.tasks.domain.task_factory import TaskFactory
from agentarea.modules.tasks.infrastructure.repository import TaskRepositoryInterface

logger = logging.getLogger(__name__)


class TaskService:
    """Service for creating and managing tasks."""

    def __init__(self, event_broker: EventBroker, task_repository: TaskRepositoryInterface):
        self.event_broker = event_broker
        self.task_repository = task_repository

    async def create_and_start_test_task(self, agent_id: UUID) -> Task:
        """Create a test task and automatically start agent execution."""
        try:
            # Create test task
            task = TaskFactory.create_test_task(agent_id)

            # Save task to repository
            task = await self.task_repository.create(task)

            logger.info(f"Created test task {task.id} for agent {agent_id}")

            # Publish TaskCreated event to trigger agent execution
            task_created_event = TaskCreated(
                task_id=task.id,
                agent_id=agent_id,
                description=task.description,
                parameters=task.parameters,
                metadata=task.metadata,
            )

            await self.event_broker.publish(task_created_event)
            logger.info(f"Published TaskCreated event for task {task.id}")

            return task

        except Exception as e:
            logger.error(f"Failed to create and start test task: {e}", exc_info=True)
            raise

    async def create_simple_task(
        self,
        title: str,
        description: str,
        task_type: TaskType = TaskType.ANALYSIS,
        priority: TaskPriority = TaskPriority.MEDIUM,
        parameters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        created_by: str | None = None,
    ) -> Task:
        """Create a simple task without assigning it to an agent or starting execution."""
        try:
            # Create task
            task = TaskFactory.create_simple_task(
                title=title,
                description=description,
                agent_id=None,  # No agent assignment
                task_type=task_type,
                priority=priority,
                parameters=parameters,
                metadata=metadata or {},
            )

            # Set created_by if provided
            if created_by:
                task.created_by = created_by

            # Save task to repository
            task = await self.task_repository.create(task)

            logger.info(f"Created task {task.id} '{title}' (unassigned)")

            return task

        except Exception as e:
            logger.error(f"Failed to create task: {e}", exc_info=True)
            raise

    async def create_and_start_simple_task(
        self,
        title: str,
        description: str,
        agent_id: UUID,
        task_type: TaskType = TaskType.ANALYSIS,
        priority: TaskPriority = TaskPriority.MEDIUM,
        parameters: dict[str, Any] | None = None,
    ) -> Task:
        """Create a simple task and automatically start agent execution."""
        try:
            # Create task
            task = TaskFactory.create_simple_task(
                title=title,
                description=description,
                agent_id=agent_id,
                task_type=task_type,
                priority=priority,
                parameters=parameters,
            )

            # Save task to repository
            task = await self.task_repository.create(task)

            logger.info(f"Created task {task.id} '{title}' for agent {agent_id}")

            # Start task execution
            await self.start_task_execution(task)

            return task

        except Exception as e:
            logger.error(f"Failed to create and start task: {e}", exc_info=True)
            raise

    async def start_task_execution(self, task: Task) -> None:
        """Start execution of a previously created task."""
        if not task.assigned_agent_id:
            raise ValueError(f"Cannot start execution of task {task.id}: No agent assigned")

        try:
            # Publish TaskCreated event to trigger agent execution
            task_created_event = TaskCreated(
                task_id=task.id,
                agent_id=task.assigned_agent_id,
                description=task.description,
                parameters=task.parameters,
                metadata=task.metadata,
            )

            await self.event_broker.publish(task_created_event)
            logger.info(f"Published TaskCreated event for task {task.id}")

        except Exception as e:
            logger.error(f"Failed to start task execution: {e}", exc_info=True)
            raise

    async def create_and_start_mcp_task(
        self,
        title: str,
        description: str,
        mcp_server_id: str,
        tool_name: str,
        agent_id: UUID,
        tool_configuration: dict[str, Any] | None = None,
        priority: TaskPriority = TaskPriority.MEDIUM,
    ) -> Task:
        """Create an MCP integration task and start agent execution."""
        try:
            # Create MCP task
            task = TaskFactory.create_mcp_integration_task(
                title=title,
                description=description,
                mcp_server_id=mcp_server_id,
                tool_name=tool_name,
                agent_id=agent_id,
                tool_configuration=tool_configuration,
                priority=priority,
            )

            # Save task to repository
            task = await self.task_repository.create(task)

            logger.info(f"Created MCP task {task.id} for server {mcp_server_id}, tool {tool_name}")

            # Start task execution
            await self.start_task_execution(task)

            return task

        except Exception as e:
            logger.error(f"Failed to create and start MCP task: {e}", exc_info=True)
            raise

    # --------------------------------------------------------------------- #
    # New functionality                                                     #
    # --------------------------------------------------------------------- #

    async def get_tasks_by_user(
        self, user_id: str, limit: int = 100, offset: int = 0
    ) -> list[Task]:
        """Retrieve tasks created by a specific user."""
        logger.debug("Fetching tasks for user %s (limit=%s offset=%s)", user_id, limit, offset)
        return await self.task_repository.get_by_user_id(user_id, limit, offset)

    async def get_tasks_by_agent(
        self, agent_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[Task]:
        """Retrieve tasks assigned to a specific agent."""
        logger.debug("Fetching tasks for agent %s (limit=%s offset=%s)", agent_id, limit, offset)
        return await self.task_repository.get_by_agent_id(agent_id, limit, offset)

    async def assign_task_to_agent(
        self, task_id: str, agent_id: UUID, assigned_by: str | None = None
    ) -> Task:
        """Assign an existing task to an agent."""
        logger.info(
            "Assigning task %s to agent %s (assigned_by=%s)", task_id, agent_id, assigned_by
        )
        task = await self.task_repository.get_by_id(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        if not task.can_be_assigned():
            raise ValueError(f"Task {task_id} cannot be assigned (status={task.status.state})")

        task.assign_to_agent(agent_id, assigned_by)
        await self.task_repository.update(task)
        return task

    async def get_pending_tasks(self, limit: int = 20) -> list[Task]:
        """Retrieve tasks that are pending assignment to an agent."""
        logger.debug("Fetching up to %s pending tasks", limit)
        return await self.task_repository.get_pending_tasks(limit)
