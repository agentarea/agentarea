"""Temporal-based task manager implementation.

This module provides a task manager that integrates with Temporal workflows
for task execution. It implements the BaseTaskManager interface and handles
task execution through Temporal workflows.
"""

import logging
from typing import Any, Optional
from uuid import UUID

from agentarea_common.workflow.temporal_executor import TemporalWorkflowExecutor
from agentarea_common.workflow.executor import WorkflowConfig

from .domain.interfaces import BaseTaskManager
from .domain.models import SimpleTask
from .infrastructure.repository import TaskRepository

logger = logging.getLogger(__name__)


class TemporalTaskManager(BaseTaskManager):
    """Task manager that uses Temporal workflows for task execution."""
    
    def __init__(self, task_repository: TaskRepository):
        """Initialize with TaskRepository dependency."""
        self.task_repository = task_repository
        self.temporal_executor = TemporalWorkflowExecutor()
    
    async def submit_task(self, task: SimpleTask) -> SimpleTask:
        """Submit a task for execution."""
        try:
            logger.info(f"Submitting task {task.id} for execution")
            
            # Start temporal workflow for task execution
            workflow_id = f"task-{task.id}"
            
            # Create AgentExecutionRequest format
            from agentarea_execution.models import AgentExecutionRequest
            
            execution_request = AgentExecutionRequest(
                task_id=task.id,
                agent_id=task.agent_id,
                user_id=task.user_id,
                task_query=task.query,
                task_parameters=task.task_parameters or {},
                workflow_metadata={}
            )
            
            # Start the workflow using the correct workflow name and arguments
            # Convert dataclass to dict for JSON serialization
            args_dict = {
                "task_id": str(execution_request.task_id),
                "agent_id": str(execution_request.agent_id),
                "user_id": execution_request.user_id,
                "task_query": execution_request.task_query,
                "task_parameters": execution_request.task_parameters,
                "timeout_seconds": execution_request.timeout_seconds,
                "max_reasoning_iterations": execution_request.max_reasoning_iterations,
                "enable_agent_communication": execution_request.enable_agent_communication,
                "requires_human_approval": execution_request.requires_human_approval,
                "workflow_metadata": execution_request.workflow_metadata
            }
            
            # Create workflow config with task queue
            config = WorkflowConfig(
                task_queue="agent-tasks"  # Use the same task queue as the worker
            )
            
            await self.temporal_executor.start_workflow(
                workflow_name="AgentExecutionWorkflow",
                workflow_id=workflow_id,
                args=args_dict,
                config=config
            )
            
            # Update task status to submitted
            task.status = "submitted"
            updated_task = await self.task_repository.update(task)
            
            logger.info(f"Task {task.id} submitted successfully")
            return updated_task

        except Exception as e:
            logger.error(f"Error submitting task {task.id}: {e}", exc_info=True)
            # Update task status to failed
            task.status = "failed"
            task.error_message = str(e)
            await self.task_repository.update(task)
            raise
    
    async def get_task(self, task_id: UUID) -> Optional[SimpleTask]:
        """Get task by ID."""
        return await self.task_repository.get(task_id)
    
    async def cancel_task(self, task_id: UUID) -> bool:
        """Cancel a task."""
        try:
            logger.info(f"Cancelling task {task_id}")
            
            # Get task from database
            task = await self.task_repository.get(task_id)
            if not task:
                logger.warning(f"Task {task_id} not found")
                return False
            
            # Cancel temporal workflow
            workflow_id = f"task-{task_id}"
            await self.temporal_executor.cancel_workflow(workflow_id)
            
            # Update task status
            task.status = "cancelled"
            await self.task_repository.update(task)
            
            logger.info(f"Task {task_id} cancelled successfully")
            return True

        except Exception as e:
            logger.error(f"Error cancelling task {task_id}: {e}", exc_info=True)
            return False
    
    async def list_tasks(
        self,
        agent_id: Optional[UUID] = None,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> list[SimpleTask]:
        """List tasks with optional filtering."""
        # For now, return all tasks since repository doesn't support filtering
        return await self.task_repository.list()
    
    async def get_task_status(self, task_id: UUID) -> Optional[str]:
        """Get task status."""
        task = await self.task_repository.get(task_id)
        return task.status if task else None
    
    async def get_task_result(self, task_id: UUID) -> Optional[Any]:
        """Get task result."""
        task = await self.task_repository.get(task_id)
        return task.result if task else None
