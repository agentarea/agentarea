"""Simple task service for AgentArea platform.

Coordinates task creation and execution with agent_runner_service.
"""

import logging
from typing import Any, AsyncGenerator
from uuid import UUID

from agentarea_common.events.broker import EventBroker

from agentarea_tasks.domain.models import SimpleTask
from agentarea_tasks.infrastructure.repository import TaskRepository

logger = logging.getLogger(__name__)


class TaskService:
    """Simple service for managing tasks and coordinating with agent execution."""
    
    def __init__(
        self,
        task_repository: TaskRepository,
        event_broker: EventBroker,
        agent_runner_service: Any,  # Avoid circular import
    ):
        self.task_repository = task_repository
        self.event_broker = event_broker
        self.agent_runner_service = agent_runner_service

    async def create_task(
        self,
        title: str,
        description: str,
        query: str,
        user_id: str,
        agent_id: UUID,
        task_parameters: dict[str, Any] | None = None,
    ) -> SimpleTask:
        """Create a new task for agent execution."""
        task = SimpleTask(
            title=title,
            description=description,
            query=query,
            user_id=user_id,
            agent_id=agent_id,
            task_parameters=task_parameters or {},
            status="submitted",
        )
        
        # Persist the task
        created_task = await self.task_repository.create(task)
        logger.info(f"Created task {created_task.id} for agent {agent_id}")
        
        return created_task

    async def execute_task(
        self,
        task_id: UUID,
        enable_agent_communication: bool = False,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute a task using the agent runner service."""
        # Get the task
        task = await self.task_repository.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
            
        logger.info(f"Starting execution of task {task_id}")
        
        # Update task status to working
        task.status = "working"
        await self.task_repository.update(task)
        
        try:
            # Execute via agent runner service
            async for event in self.agent_runner_service.run_agent_task(
                agent_id=task.agent_id,
                task_id=str(task_id),
                user_id=task.user_id,
                query=task.query,
                task_parameters=task.task_parameters,
                enable_agent_communication=enable_agent_communication,
            ):
                # Update task based on events
                await self._handle_agent_event(task_id, event)
                yield event
                
        except Exception as e:
            logger.error(f"Error executing task {task_id}: {e}")
            # Update task with error
            task.status = "failed"
            task.error_message = str(e)
            await self.task_repository.update(task)
            raise

    async def create_and_execute_task(
        self,
        title: str,
        description: str,
        query: str,
        user_id: str,
        agent_id: UUID,
        task_parameters: dict[str, Any] | None = None,
        enable_agent_communication: bool = False,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Create a task and immediately start execution."""
        # Create the task
        task = await self.create_task(
            title=title,
            description=description,
            query=query,
            user_id=user_id,
            agent_id=agent_id,
            task_parameters=task_parameters,
        )
        
        # Execute it
        async for event in self.execute_task(task.id, enable_agent_communication):
            yield event

    async def get_task(self, task_id: UUID) -> SimpleTask | None:
        """Get a task by ID."""
        return await self.task_repository.get(task_id)
        
    async def get_user_tasks(
        self, user_id: str, limit: int = 100, offset: int = 0
    ) -> list[SimpleTask]:
        """Get tasks for a specific user."""
        return await self.task_repository.get_by_user_id(user_id, limit, offset)
        
    async def get_agent_tasks(
        self, agent_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[SimpleTask]:
        """Get tasks for a specific agent."""
        return await self.task_repository.get_by_agent_id(agent_id, limit, offset)

    async def _handle_agent_event(self, task_id: UUID, event: dict[str, Any]) -> None:
        """Handle events from agent execution to update task status."""
        event_type = event.get("event_type", "")
        
        # Get current task
        task = await self.task_repository.get(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found for event {event_type}")
            return
            
        # Update based on event type
        if event_type == "TaskCompleted":
            task.status = "completed"
            task.result = event.get("result", {})
            await self.task_repository.update(task)
            logger.info(f"Task {task_id} completed successfully")
            
        elif event_type == "TaskFailed":
            task.status = "failed"
            task.error_message = event.get("error_message", "Unknown error")
            await self.task_repository.update(task)
            logger.error(f"Task {task_id} failed: {task.error_message}")
            
        elif event_type == "TaskStatusChanged":
            new_status = event.get("new_status", "")
            if new_status:
                task.status = new_status
                await self.task_repository.update(task)
                logger.info(f"Task {task_id} status changed to {new_status}")
