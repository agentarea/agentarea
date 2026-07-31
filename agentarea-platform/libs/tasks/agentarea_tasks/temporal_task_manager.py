"""Temporal-based task manager implementation.

This module provides a task manager that integrates with Temporal workflows
for task execution. It implements the BaseTaskManager interface and handles
task execution through Temporal workflows.
"""

import logging
from typing import Any
from uuid import UUID

from agentarea_common.workflow.executor import WorkflowConfig
from agentarea_common.workflow.temporal_executor import TemporalWorkflowExecutor
from agentarea_execution.models import AgentExecutionRequest

from .domain.interfaces import BaseTaskManager
from .domain.models import AgentTask
from .infrastructure.repository import TaskRepository

logger = logging.getLogger(__name__)


class TemporalTaskManager(BaseTaskManager):
    """Task manager that uses Temporal workflows for task execution."""

    def __init__(self, task_repository: TaskRepository):
        """Initialize with TaskRepository dependency."""
        from agentarea_common.config import get_settings

        self.task_repository = task_repository

        # Get settings and configure Temporal executor properly
        settings = get_settings()
        self.temporal_executor = TemporalWorkflowExecutor(
            namespace=settings.workflow.TEMPORAL_NAMESPACE,
            server_url=settings.workflow.TEMPORAL_SERVER_URL,
        )

    def _task_to_agent_task(self, task) -> AgentTask:
        """Convert Task domain model to AgentTask."""
        from .domain.models import AgentTask

        # Handle different field names between Task domain model and TaskORM
        user_id = getattr(task, "user_id", None) or getattr(task, "created_by", None)
        workspace_id = getattr(task, "workspace_id", None)

        if not workspace_id:
            raise ValueError(
                f"Task {task.id} missing required workspace_id. "
                "All tasks must have a workspace_id for proper multi-tenancy isolation."
            )

        if not user_id:
            raise ValueError(
                f"Task {task.id} missing required user_id or created_by. "
                "All tasks must have a user_id for proper audit tracking."
            )

        # Handle metadata field - could be dict, SQLAlchemy MetaData, or None
        metadata_raw = getattr(task, "metadata", None) or getattr(task, "task_metadata", None)
        if metadata_raw is None:
            metadata = {}
        elif isinstance(metadata_raw, dict):
            metadata = metadata_raw
        else:
            # If it's not a dict (e.g., SQLAlchemy MetaData), convert to empty dict
            metadata = {}

        governance_snapshot = metadata.get("governance_snapshot")
        effective_policy = (
            governance_snapshot.get("effective_policy")
            if isinstance(governance_snapshot, dict)
            else None
        )

        return AgentTask(
            id=task.id,
            title=task.description,  # Use description as title
            description=task.description,
            query=task.description,  # Use description as query
            user_id=user_id,
            workspace_id=workspace_id,
            agent_id=task.agent_id,
            status=task.status,
            task_parameters=task.parameters or {},
            result=task.result,
            error_message=task.error,
            created_at=task.created_at,
            updated_at=task.updated_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            execution_id=task.execution_id,
            metadata=metadata,
            effective_policy=effective_policy,
        )

    def _agent_task_to_task(self, agent_task: AgentTask):
        """Convert AgentTask to Task domain model."""
        from .domain.models import Task

        return Task(
            id=agent_task.id,
            agent_id=agent_task.agent_id,
            description=agent_task.description,
            parameters=agent_task.task_parameters,
            status=agent_task.status,
            result=agent_task.result,
            error=agent_task.error_message,
            created_at=agent_task.created_at,
            updated_at=agent_task.updated_at or agent_task.created_at,
            started_at=agent_task.started_at,
            completed_at=agent_task.completed_at,
            execution_id=agent_task.execution_id,
            user_id=agent_task.user_id,  # This will be mapped to created_by in the repository
            workspace_id=agent_task.workspace_id,
            metadata=agent_task.metadata,
        )

    async def submit_task(self, task: AgentTask) -> AgentTask:
        """Submit a task for execution."""
        try:
            logger.info(f"Submitting task {task.id} for execution")

            # Start temporal workflow for task execution
            workflow_id = f"task-{task.id}"

            # Validate workspace_id is present
            if not task.workspace_id:
                raise ValueError(
                    f"Task {task.id} missing required workspace_id. "
                    "All tasks must have a workspace_id for proper multi-tenancy isolation."
                )

            # Create AgentExecutionRequest format
            execution_request = AgentExecutionRequest(
                task_id=task.id,
                agent_id=task.agent_id,
                user_id=task.user_id,
                workspace_id=task.workspace_id,
                task_query=task.query,
                task_parameters=task.task_parameters or {},
                requires_human_approval=bool(
                    (task.metadata or {}).get("requires_human_approval", False)
                ),
                workflow_metadata=task.metadata or {},
                effective_policy=task.effective_policy,
            )

            # Start the workflow using the correct workflow name and arguments
            # Convert dataclass to dict for JSON serialization
            args_dict = {
                "task_id": str(execution_request.task_id),
                "agent_id": str(execution_request.agent_id),
                "user_id": execution_request.user_id,
                "workspace_id": execution_request.workspace_id,
                "task_query": execution_request.task_query,
                "task_parameters": execution_request.task_parameters,
                "requires_human_approval": execution_request.requires_human_approval,
                "workflow_metadata": execution_request.workflow_metadata,
                "effective_policy": execution_request.effective_policy,
            }

            # Activity retries handle transient failures at the side-effect boundary.
            # Retrying the whole agent workflow would replay a fresh run after a
            # terminal failure and can execute shell/MCP side effects again.
            config = WorkflowConfig(
                task_queue="agent-tasks",
                retry_attempts=1,
            )

            # Debug: Log args_dict to verify workspace_id is present
            logger.info(f"Starting workflow {workflow_id} with args: {args_dict}")
            logger.info(f"workspace_id in args_dict: {args_dict.get('workspace_id')}")

            execution_id = await self.temporal_executor.start_workflow(
                workflow_name="AgentExecutionWorkflow",
                workflow_id=workflow_id,
                args=args_dict,
                config=config,
            )

            # Update task status to running (not submitted) since workflow started successfully
            # Also set the execution_id for tracking
            updated_task_domain = await self.task_repository.update_status(task.id, "running")
            if updated_task_domain:
                # Set execution_id on the task
                updated_task_domain.execution_id = execution_id
                updated_task_domain = await self.task_repository.update_task(updated_task_domain)

            if updated_task_domain:
                updated_agent_task = self._task_to_agent_task(updated_task_domain)
                logger.info(f"Task {task.id} submitted successfully")
                return updated_agent_task
            else:
                raise Exception(f"Failed to update task {task.id} status")

        except Exception as e:
            logger.error(f"Error submitting task {task.id}: {e}", exc_info=True)
            # Update task status to failed
            task.status = "failed"
            task.error_message = str(e)
            # Convert and update in repository
            task_domain = self._agent_task_to_task(task)
            await self.task_repository.update_task(task_domain)
            raise

    async def get_task(self, task_id: UUID) -> AgentTask | None:
        """Get task by ID."""
        task_domain = await self.task_repository.get_task(task_id)
        if task_domain:
            return self._task_to_agent_task(task_domain)
        return None

    async def cancel_task(self, task_id: UUID) -> bool:
        """Cancel a task."""
        try:
            logger.info(f"Cancelling task {task_id}")

            # Get task from database
            task_domain = await self.task_repository.get_task(task_id)
            if not task_domain:
                logger.warning(f"Task {task_id} not found")
                return False

            # Cancel temporal workflow
            workflow_id = f"task-{task_id}"
            await self.temporal_executor.cancel_workflow(workflow_id)

            # Update task status
            await self.task_repository.update_status(task_id, "cancelled")

            logger.info(f"Task {task_id} cancelled successfully")
            return True

        except Exception as e:
            logger.error(f"Error cancelling task {task_id}: {e}", exc_info=True)
            return False

    async def list_tasks(
        self,
        agent_id: UUID | None = None,
        user_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AgentTask]:
        """List tasks with optional filtering."""
        # Get tasks from repository and convert to AgentTask
        tasks_domain = await self.task_repository.list_tasks(limit=limit, offset=offset)
        return [self._task_to_agent_task(task) for task in tasks_domain]

    async def get_task_status(self, task_id: UUID) -> str | None:
        """Get task status."""
        task_domain = await self.task_repository.get_task(task_id)
        return task_domain.status if task_domain else None

    async def get_task_result(self, task_id: UUID) -> Any | None:
        """Get task result."""
        task_domain = await self.task_repository.get_task(task_id)
        return task_domain.result if task_domain else None
