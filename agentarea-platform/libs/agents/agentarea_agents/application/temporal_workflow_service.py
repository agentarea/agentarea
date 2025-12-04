import logging
from typing import Any
from uuid import UUID

from agentarea_agents.domain.interfaces import ExecutionServiceInterface

from ..domain.interfaces import ExecutionRequest

logger = logging.getLogger(__name__)


class TemporalWorkflowService:
    def __init__(self, execution_service: ExecutionServiceInterface):
        self._execution_service = execution_service

    async def execute_agent_task_async(
        self,
        agent_id: UUID,
        task_query: str,
        user_id: str,
        session_id: str | None = None,
        task_parameters: dict[str, Any] | None = None,
        timeout_seconds: int = 300,
    ) -> dict[str, Any]:
        try:
            request = ExecutionRequest(
                agent_id=agent_id,
                task_query=task_query,
                user_id=user_id,
                session_id=session_id,
                task_parameters=task_parameters,
                timeout_seconds=timeout_seconds,
            )
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
        try:
            return await self._execution_service.cancel_execution(execution_id)
        except Exception as e:
            logger.error(f"Failed to cancel task: {e}")
            return False

    async def pause_task(self, execution_id: str) -> bool:
        try:
            return await self._execution_service.pause_execution(execution_id)
        except Exception as e:
            logger.error(f"Failed to pause task: {e}")
            return False

    async def resume_task(self, execution_id: str) -> bool:
        try:
            return await self._execution_service.resume_execution(execution_id)
        except Exception as e:
            logger.error(f"Failed to resume task: {e}")
            return False
