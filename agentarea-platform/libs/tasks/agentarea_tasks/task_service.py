"""Task service for AgentArea platform.

High-level service that orchestrates task management by:
1. Handling task persistence through TaskRepository
2. Delegating task execution to injected TaskManager
3. Managing task lifecycle and events
4. Validating agent existence before task submission
"""

import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from agentarea_common.events.broker import EventBroker

from .domain.base_service import BaseTaskService
from .domain.interfaces import BaseTaskManager
from .domain.models import SimpleTask
from .infrastructure.repository import TaskRepository

if TYPE_CHECKING:
    from agentarea_common.base import RepositoryFactory

logger = logging.getLogger(__name__)


class TaskService(BaseTaskService):
    """High-level service for task management that orchestrates persistence and execution."""

    def __init__(
        self,
        repository_factory: "RepositoryFactory",
        event_broker: EventBroker,
        task_manager: BaseTaskManager,
        workflow_service: Any | None = None,
    ):
        """Initialize with repository factory, event broker, task manager, and
        optional dependencies.
        """
        # Create repositories using factory
        task_repository = repository_factory.create_repository(TaskRepository)
        super().__init__(task_repository, event_broker)

        self.repository_factory = repository_factory
        self.task_manager = task_manager
        self.workflow_service = workflow_service

        # Create agent repository using factory for validation
        try:
            from agentarea_agents.infrastructure.repository import AgentRepository

            self.agent_repository = repository_factory.create_repository(AgentRepository)
        except ImportError:
            self.agent_repository = None

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
        workspace_id: str | None = None,
        task_parameters: dict[str, Any] | None = None,
    ) -> SimpleTask:
        """Create a new task from parameters."""
        task = SimpleTask(
            title=title,
            description=description,
            query=query,
            user_id=user_id,
            workspace_id=workspace_id,
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
        self, agent_id: UUID, limit: int = 100, offset: int = 0, creator_scoped: bool = False
    ) -> list[SimpleTask]:
        """Get tasks for a specific agent."""
        # Get Task domain models from repository and convert to SimpleTask
        if hasattr(self.task_repository, "list_all"):
            # Get raw TaskORM objects from workspace repository
            task_orms = await self.task_repository.list_all(
                creator_scoped=creator_scoped, limit=limit, offset=offset, agent_id=agent_id
            )
            # Convert TaskORM -> Task -> SimpleTask
            tasks = [self.task_repository._orm_to_domain(task_orm) for task_orm in task_orms]
            return [self._task_to_simple_task(task) for task in tasks]
        else:
            # Fallback for repositories that don't support workspace scoping
            return await self.list_tasks(agent_id=agent_id, limit=limit, offset=offset)

    async def get_task_status(self, task_id: UUID) -> str | None:
        """Get task status."""
        task = await self.get_task(task_id)
        return task.status if task else None

    async def get_task_result(self, task_id: UUID) -> Any | None:
        """Get task result."""
        task = await self.get_task(task_id)
        return task.result if task else None

    async def get_recent_tasks(
        self,
        limit: int = 100,
        workspace_id: str | None = None,
        hours: int = 168,  # Default to 7 days
    ) -> list[SimpleTask]:
        """Get recent tasks within a time period for monitoring and analytics.

        Args:
            limit: Maximum number of tasks to return
            workspace_id: Workspace ID to filter by (optional)
            hours: Number of hours back to look (default 7 days)

        Returns:
            List of recent tasks ordered by creation time (newest first)
        """
        from datetime import timedelta

        # Calculate cutoff time
        cutoff_time = datetime.now(UTC) - timedelta(hours=hours)

        try:
            if hasattr(self.task_repository, "list_all"):
                # Use workspace-aware repository method
                # Note: The base repository doesn't support created_after filtering yet,
                # so we'll get all recent tasks and filter in memory for now
                task_orms = await self.task_repository.list_all(
                    limit=limit * 2,  # Get more to account for time filtering
                    offset=0,
                )
                # Convert TaskORM -> Task -> SimpleTask and filter by time
                tasks = []
                for task_orm in task_orms:
                    task = self.task_repository._orm_to_domain(task_orm)
                    simple_task = self._task_to_simple_task(task)

                    # Filter by time and workspace
                    if simple_task.created_at and simple_task.created_at >= cutoff_time:
                        if workspace_id is None or simple_task.workspace_id == workspace_id:
                            tasks.append(simple_task)

                    if len(tasks) >= limit:
                        break

                # Sort by creation time (newest first)
                tasks.sort(
                    key=lambda t: t.created_at or datetime.min.replace(tzinfo=UTC), reverse=True
                )
                return tasks[:limit]
            else:
                # Fallback for repositories without workspace scoping
                # Get all tasks and filter in memory (not ideal for production)
                all_tasks = await self.list_tasks(
                    limit=limit * 2
                )  # Get more to account for filtering

                # Filter by time and workspace
                filtered_tasks = []
                for task in all_tasks:
                    if task.created_at and task.created_at >= cutoff_time:
                        if workspace_id is None or task.workspace_id == workspace_id:
                            filtered_tasks.append(task)

                    if len(filtered_tasks) >= limit:
                        break

                # Sort by creation time (newest first)
                filtered_tasks.sort(
                    key=lambda t: t.created_at or datetime.min.replace(tzinfo=UTC), reverse=True
                )
                return filtered_tasks[:limit]

        except Exception as e:
            logger.error(f"Failed to get recent tasks: {e}")
            # Return empty list on error to not break monitoring
            return []

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
        task.update_status(status, execution_id=execution_id, result=result, error_message=error)

        # Persist the update
        return await self.update_task(task)

    async def list_agent_tasks(
        self, agent_id: UUID, limit: int = 100, creator_scoped: bool = False
    ) -> list[SimpleTask]:
        """List tasks for an agent.

        This method provides compatibility with the application layer TaskService
        that was removed during refactoring.

        Args:
            agent_id: The agent ID to get tasks for
            limit: Maximum number of tasks to return
            creator_scoped: If True, only return tasks created by current user

        Returns:
            List of tasks for the agent
        """
        return await self.get_agent_tasks(agent_id, limit=limit, creator_scoped=creator_scoped)

    async def list_agent_tasks_with_workflow_status(
        self, agent_id: UUID, limit: int = 100, creator_scoped: bool = False
    ) -> list[SimpleTask]:
        """List tasks for an agent enriched with workflow status.

        Args:
            agent_id: The agent ID to get tasks for
            limit: Maximum number of tasks to return
            creator_scoped: If True, only return tasks created by current user

        Returns:
            List of tasks for the agent with current workflow status
        """
        tasks = await self.list_agent_tasks(agent_id, limit, creator_scoped=creator_scoped)

        if not self.workflow_service:
            logger.warning(
                "Workflow service not available - returning tasks without workflow enrichment"
            )
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
            logger.warning(
                "Workflow service not available - returning task without workflow enrichment"
            )
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
        workspace_id: str,
        parameters: dict[str, Any] | None = None,
        user_id: str | None = None,
        enable_agent_communication: bool = True,
        requires_human_approval: bool = False,
    ) -> SimpleTask:
        """Create a task and execute it using workflow.

        Args:
            agent_id: The agent to execute the task
            description: Task description
            workspace_id: Workspace ID (required for proper multi-tenancy isolation)
            parameters: Task parameters
            user_id: User ID
            enable_agent_communication: Whether to enable agent communication
            requires_human_approval: Whether this task requires human approval before running

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
            user_id=user_id,
            workspace_id=workspace_id,  # Required, no fallback
            agent_id=agent_id,
            status="pending",
            task_parameters=parameters or {},
            metadata={
                "created_via": "api",
                "agent_name": agent_name,
                "enable_agent_communication": enable_agent_communication,
                "requires_human_approval": requires_human_approval,
            },
        )

        # Store task
        stored_task = await self.create_task(task)

        # Publish TaskCreated event - temporarily disabled due to event creation issue
        # from .domain.events import TaskCreated
        # task_created_event = TaskCreated(
        #     task_id=str(task_id),
        #     agent_id=str(agent_id),
        #     description=description,
        #     parameters=parameters or {},
        # )
        # await self._publish_task_event(task_created_event)

        # Set initial status
        stored_task.status = "pending"

        # Execute task using the task manager (which uses AgentExecutionWorkflow)
        try:
            # Submit task through task manager
            executed_task = await self.task_manager.submit_task(stored_task)

            # Update stored task with execution info
            stored_task.status = executed_task.status
            stored_task.execution_id = executed_task.execution_id

            logger.info(f"Task {task_id} submitted successfully with status {executed_task.status}")

        except Exception as e:
            logger.error(f"Failed to submit task: {e}")
            stored_task.status = "failed"
            stored_task.result = {"error": str(e), "error_type": "task_submission_failed"}

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

    async def _get_historical_events(self, task_id: UUID) -> list[dict[str, Any]]:
        """Get historical events for a task from the database with proper session management."""
        try:
            from agentarea_common.config.database import get_database
            from sqlalchemy import text

            # Use proper database session management to avoid connection leaks
            db = get_database()

            async with db.get_db() as session:
                # Query historical events from database
                query = text("""
                    SELECT event_type, timestamp, data, metadata
                    FROM task_events
                    WHERE task_id = :task_id
                    ORDER BY timestamp ASC
                """)

                result = await session.execute(query, {"task_id": str(task_id)})
                rows = result.fetchall()

                # Convert database rows to event format
                historical_events = []
                for row in rows:
                    historical_events.append(
                        {
                            "event_type": row.event_type,
                            "timestamp": row.timestamp.isoformat(),
                            "data": dict(row.data) if row.data else {},
                        }
                    )

                logger.debug(
                    f"Retrieved {len(historical_events)} historical events for task {task_id}"
                )
                return historical_events

        except Exception as e:
            logger.error(f"Failed to get historical events for task {task_id}: {e}")
            # Return empty list on error to not break SSE streaming
            return []

    def _format_protocol_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Format event using protocol structure with rich data, no metadata pollution.

        This method formats events according to the BaseWorkflowEvent protocol structure,
        ensuring consistent format across all transport mechanisms (SSE, REST, WebSocket).
        """
        event_type = event.get("event_type", "unknown")
        data = event.get("data", {})

        # Create protocol-compliant event structure
        protocol_event = {
            "event_type": event_type,
            "event_id": data.get("event_id") or event.get("event_id") or str(uuid4()),
            "timestamp": event.get("timestamp", datetime.now(UTC).isoformat()),
            "data": {
                # Core workflow event data
                "task_id": data.get("task_id", ""),
                "agent_id": data.get("agent_id", ""),
                "execution_id": data.get("execution_id", ""),
                "iteration": data.get("iteration"),
                # Event-specific data (preserve all original data)
                **{
                    k: v
                    for k, v in data.items()
                    if k not in ["task_id", "agent_id", "execution_id", "iteration", "event_id"]
                },
            },
        }

        return protocol_event
