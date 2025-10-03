"""Clean execution service implementation without mocks."""

import logging
from typing import Any
from uuid import uuid4

from ..domain.interfaces import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionServiceInterface,
)

logger = logging.getLogger(__name__)


class ExecutionService(ExecutionServiceInterface):
    """Clean execution service that delegates to workflow orchestrators."""

    def __init__(self, workflow_orchestrator: "WorkflowOrchestratorInterface"):
        self._workflow_orchestrator = workflow_orchestrator

    async def execute_async(self, request: ExecutionRequest) -> ExecutionResult:
        """Execute agent task via workflow orchestrator."""
        try:
            task_id = str(uuid4())
            execution_id = f"agent-task-{task_id}"

            # Delegate to workflow orchestrator
            result = await self._workflow_orchestrator.start_workflow(
                execution_id=execution_id, request=request
            )

            return ExecutionResult(
                task_id=task_id,
                execution_id=execution_id,
                success=result.get("success", True),
                status=result.get("status", "started"),
                content=result.get("content", "Task started"),
                metadata=result.get("metadata", {}),
            )

        except Exception as e:
            logger.error(f"Failed to start execution: {e}")
            task_id = str(uuid4())
            execution_id = f"agent-task-{task_id}"

            return ExecutionResult(
                task_id=task_id,
                execution_id=execution_id,
                success=False,
                status="failed",
                error=str(e),
            )

    async def get_status(self, execution_id: str) -> dict[str, Any]:
        """Get execution status from workflow orchestrator."""
        try:
            return await self._workflow_orchestrator.get_workflow_status(execution_id)
        except Exception as e:
            logger.error(f"Failed to get execution status: {e}")
            return {
                "status": "error",
                "success": False,
                "error": str(e),
            }

    async def cancel_execution(self, execution_id: str) -> bool:
        """Cancel execution via workflow orchestrator."""
        try:
            return await self._workflow_orchestrator.cancel_workflow(execution_id)
        except Exception as e:
            logger.error(f"Failed to cancel execution: {e}")
            return False

    async def pause_execution(self, execution_id: str) -> bool:
        """Pause execution via workflow orchestrator."""
        try:
            return await self._workflow_orchestrator.pause_workflow(execution_id)
        except Exception as e:
            logger.error(f"Failed to pause execution: {e}")
            return False

    async def resume_execution(self, execution_id: str) -> bool:
        """Resume execution via workflow orchestrator."""
        try:
            return await self._workflow_orchestrator.resume_workflow(execution_id)
        except Exception as e:
            logger.error(f"Failed to resume execution: {e}")
            return False


# Interface for workflow orchestrators
from abc import ABC, abstractmethod  # noqa: E402


class WorkflowOrchestratorInterface(ABC):
    """Interface for workflow orchestration systems."""

    @abstractmethod
    async def start_workflow(self, execution_id: str, request: ExecutionRequest) -> dict[str, Any]:
        """Start workflow execution."""
        pass

    @abstractmethod
    async def get_workflow_status(self, execution_id: str) -> dict[str, Any]:
        """Get workflow status."""
        pass

    @abstractmethod
    async def cancel_workflow(self, execution_id: str) -> bool:
        """Cancel workflow."""
        pass

    @abstractmethod
    async def pause_workflow(self, execution_id: str) -> bool:
        """Pause workflow execution."""
        pass

    @abstractmethod
    async def resume_workflow(self, execution_id: str) -> bool:
        """Resume paused workflow execution."""
        pass
