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
        workspace_id: str | None = None,
        session_id: str | None = None,
        task_parameters: dict[str, Any] | None = None,
        timeout_seconds: int = 300,
    ) -> dict[str, Any]:
        try:
            request = ExecutionRequest(
                agent_id=agent_id,
                task_query=task_query,
                user_id=user_id,
                workspace_id=workspace_id,
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
            logger.error("Failed to execute agent task", extra={"error": str(e)})
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
            logger.error("Failed to get workflow status", extra={"error": str(e)})
            return {
                "status": "error",
                "success": False,
                "error": str(e),
            }

    async def cancel_task(self, execution_id: str) -> bool:
        try:
            return await self._execution_service.cancel_execution(execution_id)
        except Exception as e:
            logger.error("Failed to cancel task", extra={"error": str(e)})
            return False

    async def pause_task(self, execution_id: str) -> bool:
        try:
            return await self._execution_service.pause_execution(execution_id)
        except Exception as e:
            logger.error("Failed to pause task", extra={"error": str(e)})
            return False

    async def resume_task(self, execution_id: str) -> bool:
        try:
            return await self._execution_service.resume_execution(execution_id)
        except Exception as e:
            logger.error("Failed to resume task", extra={"error": str(e)})
            return False

    async def send_a2ui_action(self, execution_id: str, action_data: dict) -> bool:
        try:
            return await self._execution_service.send_a2ui_action(execution_id, action_data)
        except Exception as e:
            logger.error("Failed to send A2UI action", extra={"error": str(e)})
            return False

    async def resolve_escalation(
        self, execution_id: str, escalation_id: str, approved: bool, comment: str = ""
    ) -> bool:
        try:
            return await self._execution_service.resolve_escalation(
                execution_id, escalation_id, approved, comment
            )
        except Exception as e:
            logger.error("Failed to resolve escalation", extra={"error": str(e)})
            return False

    async def send_workflow_command(
        self, execution_id: str, command: str, payload: dict[str, Any]
    ) -> bool:
        try:
            return await self._execution_service.send_workflow_command(
                execution_id, command, payload
            )
        except Exception as e:
            logger.error("Failed to send workflow command", extra={"command": command, "error": str(e)})
            return False
