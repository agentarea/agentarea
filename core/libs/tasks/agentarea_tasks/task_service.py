"""Task service for AgentArea platform.

High-level service that orchestrates task management by:
1. Handling task persistence through TaskRepository
2. Delegating task execution to injected TaskManager
3. Managing task lifecycle and events
4. Validating agent existence before task submission
"""

import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from agentarea_common.events.broker import EventBroker

from .domain.base_service import BaseTaskService
from .domain.interfaces import BaseTaskManager
from .domain.models import SimpleTask
from .infrastructure.repository import TaskRepository

if TYPE_CHECKING:
    from agentarea_agents.infrastructure.repository import AgentRepository

logger = logging.getLogger(__name__)


class TaskService(BaseTaskService):
    """High-level service for task management that orchestrates persistence and execution."""

    def __init__(
        self,
        task_repository: TaskRepository,
        event_broker: EventBroker,
        task_manager: BaseTaskManager,
        agent_repository: Optional["AgentRepository"] = None,
        workflow_service: Any | None = None,
    ):
        """Initialize with repository, event broker, task manager, and optional dependencies."""
        super().__init__(task_repository, event_broker)
        self.task_manager = task_manager
        self.agent_repository = agent_repository
        self.workflow_service = workflow_service

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

    async def cancel_task(self, task_id: UUID) -> bool:
        """Cancel a task."""
        return await self.task_manager.cancel_task(task_id)

    async def get_user_tasks(
        self, user_id: str, limit: int = 100, offset: int = 0
    ) -> list[SimpleTask]:
        """Get tasks for a specific user."""
        return await self.list_tasks(user_id=user_id, limit=limit, offset=offset)

    async def get_agent_tasks(
        self, agent_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[SimpleTask]:
        """Get tasks for a specific agent."""
        return await self.list_tasks(agent_id=agent_id, limit=limit, offset=offset)

    async def get_task_status(self, task_id: UUID) -> str | None:
        """Get task status."""
        task = await self.get_task(task_id)
        return task.status if task else None

    async def get_task_result(self, task_id: UUID) -> Any | None:
        """Get task result."""
        task = await self.get_task(task_id)
        return task.result if task else None

    async def update_task_status(
        self,
        task_id: UUID,
        status: str,
        execution_id: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> SimpleTask | None:
        """Update task status and related fields.
        
        This method provides compatibility with the application layer TaskService
        that was removed during refactoring.
        
        Args:
            task_id: The task ID to update
            status: The new status
            execution_id: Optional execution ID
            result: Optional task result
            error: Optional error message
            
        Returns:
            The updated task if found, None otherwise
        """
        task = await self.get_task(task_id)
        if not task:
            return None

        # Update the task using the SimpleTask's update_status method
        task.update_status(
            status,
            execution_id=execution_id,
            result=result,
            error_message=error
        )

        # Persist the update
        return await self.update_task(task)

    async def list_agent_tasks(self, agent_id: UUID, limit: int = 100) -> list[SimpleTask]:
        """List tasks for an agent.
        
        This method provides compatibility with the application layer TaskService
        that was removed during refactoring.
        
        Args:
            agent_id: The agent ID to get tasks for
            limit: Maximum number of tasks to return
            
        Returns:
            List of tasks for the agent
        """
        return await self.get_agent_tasks(agent_id, limit=limit)

    async def list_agent_tasks_with_workflow_status(self, agent_id: UUID, limit: int = 100) -> list[SimpleTask]:
        """List tasks for an agent enriched with workflow status.
        
        Args:
            agent_id: The agent ID to get tasks for
            limit: Maximum number of tasks to return
            
        Returns:
            List of tasks for the agent with current workflow status
        """
        tasks = await self.list_agent_tasks(agent_id, limit)

        if not self.workflow_service:
            logger.warning("Workflow service not available - returning tasks without workflow enrichment")
            return tasks

        # Enrich each task with workflow status
        enriched_tasks = []
        for task in tasks:
            enriched_task = await self._enrich_task_with_workflow_status(task)
            enriched_tasks.append(enriched_task)

        return enriched_tasks

    async def get_task_with_workflow_status(self, task_id: UUID) -> SimpleTask | None:
        """Get a task enriched with workflow status.
        
        Args:
            task_id: The task ID to get
            
        Returns:
            Task with current workflow status if found, None otherwise
        """
        task = await self.get_task(task_id)
        if not task:
            return None

        if not self.workflow_service:
            logger.warning("Workflow service not available - returning task without workflow enrichment")
            return task

        return await self._enrich_task_with_workflow_status(task)

    async def _enrich_task_with_workflow_status(self, task: SimpleTask) -> SimpleTask:
        """Enrich a task with current workflow status.
        
        Args:
            task: The task to enrich
            
        Returns:
            Task with updated status and result from workflow
        """
        if not task.execution_id or not self.workflow_service:
            return task

        try:
            workflow_status = await self.workflow_service.get_workflow_status(task.execution_id)
            if workflow_status.get("status") != "unknown":
                # Update task with workflow status
                task.status = workflow_status.get("status", task.status)
                if workflow_status.get("result"):
                    task.result = workflow_status.get("result")
        except Exception as e:
            logger.debug(f"Could not get workflow status for task {task.id}: {e}")

        return task

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

    async def create_and_execute_task_with_workflow(
        self,
        agent_id: UUID,
        description: str,
        parameters: dict[str, Any] | None = None,
        user_id: str | None = None,
        enable_agent_communication: bool = True,
    ) -> SimpleTask:
        """Create a task and execute it using workflow.
        
        Args:
            agent_id: The agent to execute the task
            description: Task description
            parameters: Task parameters
            user_id: User ID (defaults to "api_user")
            enable_agent_communication: Whether to enable agent communication
            
        Returns:
            Created task with workflow execution info
        """
        from uuid import uuid4

        # Validate agent exists first
        await self._validate_agent_exists(agent_id)

        # Generate task ID
        task_id = uuid4()

        # Get agent name for metadata (if available)
        agent_name = "unknown"
        if self.agent_repository:
            try:
                agent = await self.agent_repository.get(agent_id)
                if agent:
                    agent_name = agent.name
            except Exception as e:
                logger.warning(f"Could not get agent name for {agent_id}: {e}")

        # Create task
        task = SimpleTask(
            id=task_id,
            title=description,
            description=description,
            query=description,
            user_id=user_id or "api_user",
            agent_id=agent_id,
            status="created",
            task_parameters=parameters or {},
            metadata={
                "created_via": "api",
                "agent_name": agent_name,
                "enable_agent_communication": enable_agent_communication,
            },
        )

        # Store task
        stored_task = await self.create_task(task)

        # Publish TaskCreated event
        from .domain.events import TaskCreated
        task_created_event = TaskCreated(
            task_id=str(task_id),
            agent_id=agent_id,
            description=description,
            parameters=parameters or {},
            metadata={
                "created_via": "api",
                "agent_name": agent_name,
                "created_at": stored_task.created_at.isoformat(),
                "user_id": user_id,
                "enable_agent_communication": enable_agent_communication,
                "status": "created",
            },
        )
        await self._publish_task_event(task_created_event)

        # Set initial status
        stored_task.status = "pending"

        # Try to execute with workflow if available
        if self.workflow_service:
            try:
                result = await self.workflow_service.execute_agent_task_async(
                    agent_id=agent_id,
                    task_query=description,
                    user_id=user_id or "api_user",
                    task_parameters=parameters or {},
                )
                execution_id = result.get("execution_id")

                # Update task with execution info
                stored_task.execution_id = execution_id
                stored_task.status = "running"

                # Publish workflow started event
                workflow_started_event = TaskCreated(
                    task_id=str(task_id),
                    agent_id=agent_id,
                    description=description,
                    parameters=parameters or {},
                    metadata={
                        "created_via": "api",
                        "agent_name": agent_name,
                        "created_at": stored_task.created_at.isoformat(),
                        "user_id": user_id,
                        "enable_agent_communication": enable_agent_communication,
                        "execution_id": execution_id,
                        "status": "running",
                        "workflow_started": True,
                    },
                )
                await self._publish_task_event(workflow_started_event)

                logger.info(f"Task {task_id} started with workflow execution ID {execution_id}")

            except Exception as e:
                logger.error(f"Failed to start task workflow: {e}")
                stored_task.status = "failed"
                stored_task.result = {"error": str(e), "error_type": "workflow_start_failed"}

                # Publish workflow failed event
                workflow_failed_event = TaskCreated(
                    task_id=str(task_id),
                    agent_id=agent_id,
                    description=description,
                    parameters=parameters or {},
                    metadata={
                        "created_via": "api",
                        "agent_name": agent_name,
                        "created_at": stored_task.created_at.isoformat(),
                        "user_id": user_id,
                        "enable_agent_communication": enable_agent_communication,
                        "status": "failed",
                        "error": str(e),
                        "workflow_failed": True,
                    },
                )
                await self._publish_task_event(workflow_failed_event)
        else:
            logger.warning("Workflow service not available - task created but not executed")

        return stored_task

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
