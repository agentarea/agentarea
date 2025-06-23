"""Workflow-based Task Execution Service.

This service uses Temporal workflows for non-blocking task execution.
"""

import logging
from datetime import timedelta
from typing import Any
from uuid import UUID

from agentarea.common.workflow.executor import TaskExecutorInterface
from agentarea.common.workflow.temporal_executor import (
    TemporalTaskExecutor,
    TemporalWorkflowExecutor,
)
from agentarea.config import get_settings

logger = logging.getLogger(__name__)


class WorkflowTaskExecutionService:
    """Non-blocking task execution service using Temporal workflows.

    This service provides async task execution that returns immediately
    while tasks run in the background via Temporal workflows.
    """

    def __init__(self, task_executor: TaskExecutorInterface | None = None):
        self.settings = get_settings()

        # Initialize task executor
        if task_executor:
            self.task_executor = task_executor
        else:
            self.task_executor = self._create_temporal_executor()

    def _create_temporal_executor(self) -> TaskExecutorInterface:
        """Create Temporal task executor."""
        workflow_settings = self.settings.workflow

        logger.info(
            f"Creating Temporal executor with server: {workflow_settings.TEMPORAL_SERVER_URL}, namespace: {workflow_settings.TEMPORAL_NAMESPACE}"
        )

        try:
            # Create workflow executor with proper configuration
            workflow_executor = TemporalWorkflowExecutor(
                namespace=workflow_settings.TEMPORAL_NAMESPACE,
                server_url=workflow_settings.TEMPORAL_SERVER_URL,
            )

            return TemporalTaskExecutor(
                workflow_executor=workflow_executor,
                default_task_queue=workflow_settings.TEMPORAL_TASK_QUEUE,
            )
        except ImportError as e:
            logger.error(f"Temporal not available: {e}")
            raise RuntimeError(f"Temporal is required but not available: {e}")
        except Exception as e:
            logger.error(f"Failed to create Temporal executor: {e}")
            raise

    async def execute_task_async(
        self,
        task_id: str,
        agent_id: UUID,
        description: str,
        user_id: str | None = None,
        task_parameters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Execute a task asynchronously - returns immediately with execution ID.

        This method provides immediate return for long-running agent tasks.

        Args:
            task_id: Unique task identifier
            agent_id: UUID of the agent to execute the task
            description: Task description/query
            user_id: User ID requesting the task
            task_parameters: Additional task parameters
            metadata: Task metadata

        Returns:
            Execution ID for tracking the workflow
        """
        logger.info(f"Starting async task execution: {task_id} for agent {agent_id}")

        # Add workflow settings to metadata
        workflow_metadata = metadata or {}
        workflow_metadata.update(
            {
                "workflow_engine": "temporal",
                "task_queue": self.settings.workflow.TEMPORAL_TASK_QUEUE,
                "enable_dynamic_activities": self.settings.task_execution.ENABLE_DYNAMIC_ACTIVITY_DISCOVERY,
            }
        )

        try:
            # Execute task using Temporal workflow - this returns immediately!
            execution_id = await self.task_executor.execute_task_async(
                task_id=task_id,
                agent_id=agent_id,
                description=description,
                user_id=user_id,
                task_parameters=task_parameters,
                metadata=workflow_metadata,
            )

            logger.info(f"Task {task_id} started with execution ID {execution_id}")
            return execution_id

        except ConnectionError as e:
            logger.error(f"Temporal connection failed for task {task_id}: {e}")
            logger.error("Please ensure Temporal server is running. Check your configuration:")
            logger.error(f"  TEMPORAL_SERVER_URL: {self.settings.workflow.TEMPORAL_SERVER_URL}")
            logger.error(f"  TEMPORAL_NAMESPACE: {self.settings.workflow.TEMPORAL_NAMESPACE}")
            logger.error(
                "To start Temporal server locally: docker run --rm -p 7233:7233 temporalio/temporal-auto-setup"
            )
            raise
        except Exception as e:
            logger.error(f"Failed to start workflow for task {task_id}: {e}")
            raise

    async def get_task_status(self, execution_id: str) -> dict[str, Any]:
        """Get current task execution status.

        Args:
            execution_id: Execution ID returned from execute_task_async

        Returns:
            Task status information including progress and results
        """
        return await self.task_executor.get_task_status(execution_id)

    async def cancel_task(self, execution_id: str) -> bool:
        """Cancel a running task.

        Args:
            execution_id: Execution ID to cancel

        Returns:
            True if cancellation was successful
        """
        return await self.task_executor.cancel_task(execution_id)

    async def wait_for_task_completion(
        self, execution_id: str, timeout: timedelta | None = None
    ) -> dict[str, Any]:
        """Wait for task completion and return result.

        Args:
            execution_id: Execution ID to wait for
            timeout: Optional timeout for waiting

        Returns:
            Task result when completed
        """
        return await self.task_executor.wait_for_task_completion(execution_id, timeout)

    # Legacy compatibility methods
    async def execute_task(
        self,
        task_id: str,
        agent_id: UUID,
        description: str,
        user_id: str | None = None,
        task_parameters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Legacy execute_task method for backward compatibility.

        This method now delegates to execute_task_async but doesn't wait
        for completion, making it non-blocking.
        """
        logger.warning(
            "execute_task() is deprecated and non-blocking. "
            "Use execute_task_async() for explicit async execution."
        )

        # Start the task but don't wait for completion
        execution_id = await self.execute_task_async(
            task_id=task_id,
            agent_id=agent_id,
            description=description,
            user_id=user_id,
            task_parameters=task_parameters,
            metadata=metadata,
        )

        logger.info(f"Legacy execute_task() started workflow {execution_id} for task {task_id}")
