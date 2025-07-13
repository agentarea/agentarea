"""Temporal Workflow Service - Clean Implementation

Delegates to execution service for proper separation of concerns.
No mocks - uses clean architecture patterns.
"""

import logging
from typing import Any
from uuid import UUID

from agentarea_agents.domain.interfaces import ExecutionServiceInterface

from ..domain.interfaces import ExecutionRequest

logger = logging.getLogger(__name__)


class TemporalWorkflowService:
    """Service for executing agent tasks via clean architecture."""

    def __init__(self, execution_service: ExecutionServiceInterface):
        # Create the clean execution service using proper DI
        self._execution_service = execution_service

    async def execute_agent_task_async(
        self,
        agent_id: UUID,
        task_query: str,
        user_id: str = "anonymous",
        session_id: str | None = None,
        task_parameters: dict[str, Any] | None = None,
        timeout_seconds: int = 300,
    ) -> dict[str, Any]:
        """Execute agent task asynchronously via clean execution service.
        
        Returns immediately with task_id and execution_id.
        """
        try:
            # Create execution request
            request = ExecutionRequest(
                agent_id=agent_id,
                task_query=task_query,
                user_id=user_id,
                session_id=session_id,
                task_parameters=task_parameters,
                timeout_seconds=timeout_seconds,
            )

            # Execute via clean service
            result = await self._execution_service.execute_async(request)

            return {
                "success": result.success,
                "task_id": result.task_id,
                "execution_id": result.execution_id,
                "status": result.status,
                "message": result.content or "Task started",
                "error": result.error,
            }

        except Exception as e:
            logger.error(f"Failed to execute agent task: {e}")
            return {
                "success": False,
                "task_id": "unknown",
                "execution_id": "unknown",
                "status": "failed",
                "error": str(e),
            }

    async def get_workflow_status(self, execution_id: str) -> dict[str, Any]:
        """Get workflow status via execution service."""
        try:
            return await self._execution_service.get_status(execution_id)
        except Exception as e:
            logger.error(f"Failed to get workflow status: {e}")
            return {
                "status": "error",
                "success": False,
                "error": str(e),
            }

    async def cancel_task(self, execution_id: str) -> bool:
        """Cancel task via execution service."""
        try:
            return await self._execution_service.cancel_execution(execution_id)
        except Exception as e:
            logger.error(f"Failed to cancel task: {e}")
            return False

    # Legacy method for backward compatibility
    async def execute_agent_task_blocking(
        self,
        agent_id: UUID,
        task_query: str,
        user_id: str = "anonymous",
        session_id: str | None = None,
        task_parameters: dict[str, Any] | None = None,
        timeout_seconds: int = 300,
    ) -> dict[str, Any]:
        """Legacy method for backward compatibility.
        
        Note: This actually returns immediately (async execution),
        despite the name. Real blocking execution would be a separate concern.
        """
        return await self.execute_agent_task_async(
            agent_id=agent_id,
            task_query=task_query,
            user_id=user_id,
            session_id=session_id,
            task_parameters=task_parameters,
            timeout_seconds=timeout_seconds,
        )
