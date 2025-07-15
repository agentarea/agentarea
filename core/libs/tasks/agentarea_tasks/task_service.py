"""Task service for AgentArea platform.

High-level service that orchestrates task management by:
1. Handling task persistence through TaskRepository
2. Delegating task execution to injected TaskManager
3. Managing task lifecycle and events
4. Validating agent existence before task submission
"""

import logging
from typing import TYPE_CHECKING, Any, AsyncGenerator, Optional
from uuid import UUID

from agentarea_common.events.broker import EventBroker

from .domain.interfaces import BaseTaskManager
from .domain.models import SimpleTask
from .infrastructure.repository import TaskRepository

if TYPE_CHECKING:
    from agentarea_agents.infrastructure.repository import AgentRepository

logger = logging.getLogger(__name__)


class TaskService:
    """High-level service for task management that orchestrates persistence and execution."""
    
    def __init__(
        self,
        task_repository: TaskRepository,
        event_broker: EventBroker,
        task_manager: BaseTaskManager,
        agent_repository: Optional["AgentRepository"] = None,
    ):
        """Initialize with repository, event broker, task manager, and optional agent repository."""
        self.task_repository = task_repository
        self.event_broker = event_broker
        self.task_manager = task_manager
        self.agent_repository = agent_repository

    async def _validate_agent_exists(self, agent_id: UUID) -> None:
        """Validate that the agent exists before processing tasks.
        
        Args:
            agent_id: The agent ID to validate
            
        Raises:
            ValueError: If agent doesn't exist or agent_repository is not available
        """
        if not self.agent_repository:
            logger.warning("Agent repository not available - skipping agent validation")
            return
            
        agent = await self.agent_repository.get(agent_id)
        if not agent:
            raise ValueError(f"Agent with ID {agent_id} does not exist")

    async def create_task(self, task: SimpleTask) -> SimpleTask:
        """Create a new task."""
        # Persist the task
        created_task = await self.task_repository.create(task)
        logger.info(f"Created task {created_task.id} for agent {task.agent_id}")
        return created_task

    async def create_task_from_params(
        self,
        title: str,
        description: str,
        query: str,
        user_id: str,
        agent_id: UUID,
        task_parameters: dict[str, Any] | None = None,
    ) -> SimpleTask:
        """Create a new task from parameters."""
        task = SimpleTask(
            title=title,
            description=description,
            query=query,
            user_id=user_id,
            agent_id=agent_id,
            task_parameters=task_parameters or {},
            status="submitted",
        )
        return await self.create_task(task)

    async def submit_task(self, task: SimpleTask) -> SimpleTask:
        """Submit a task for execution through the task manager.
        
        This method validates the agent exists before submitting to avoid
        failures later in the Temporal workflow.
        """
        # Validate agent exists first (fail fast)
        await self._validate_agent_exists(task.agent_id)
        
        # First persist the task
        created_task = await self.create_task(task)
        
        # Then submit to task manager for execution
        return await self.task_manager.submit_task(created_task)

    async def get_task(self, task_id: UUID) -> Optional[SimpleTask]:
        """Get a task by ID."""
        return await self.task_repository.get(task_id)

    async def update_task(self, task: SimpleTask) -> SimpleTask:
        """Update an existing task."""
        return await self.task_repository.update(task)

    async def cancel_task(self, task_id: UUID) -> bool:
        """Cancel a task."""
        return await self.task_manager.cancel_task(task_id)

    async def list_tasks(
        self,
        agent_id: Optional[UUID] = None,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> list[SimpleTask]:
        """List tasks with optional filtering."""
        if agent_id:
            return await self.task_repository.get_by_agent_id(agent_id, limit, offset)
        elif user_id:
            return await self.task_repository.get_by_user_id(user_id, limit, offset)
        elif status:
            return await self.task_repository.get_by_status(status)
        else:
            return await self.task_repository.list()

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

    async def get_task_status(self, task_id: UUID) -> Optional[str]:
        """Get task status."""
        task = await self.get_task(task_id)
        return task.status if task else None

    async def get_task_result(self, task_id: UUID) -> Optional[Any]:
        """Get task result."""
        task = await self.get_task(task_id)
        return task.result if task else None

    # Legacy methods for backward compatibility
    async def execute_task(
        self,
        task_id: UUID,
        enable_agent_communication: bool = False,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute a task (legacy method - prefer using submit_task)."""
        # Get the task
        task = await self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
            
        logger.info(f"Starting execution of task {task_id}")
        
        # Update task status to working
        task.status = "working"
        await self.update_task(task)
        
        try:
            # For now, just yield a completion event
            # In a real implementation, this would stream events from the task manager
            yield {"event_type": "TaskStarted", "task_id": str(task_id)}
            
            # Submit to task manager
            await self.task_manager.submit_task(task)
                
        except Exception as e:
            logger.error(f"Error executing task {task_id}: {e}")
            # Update task with error
            task.status = "failed"
            task.error_message = str(e)
            await self.update_task(task)
            yield {"event_type": "TaskFailed", "task_id": str(task_id), "error": str(e)}
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
        task = await self.create_task_from_params(
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
