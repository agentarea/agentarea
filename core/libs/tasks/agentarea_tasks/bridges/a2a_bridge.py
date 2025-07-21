"""A2A Protocol Bridge for Task Management.

This module provides a bridge between A2A protocol JSON-RPC requests
and the internal TaskService. It handles protocol conversion and
delegates to the TaskService for actual task management.
"""

import logging
from uuid import UUID

from a2a.types import (
    CancelTaskRequest,
    CancelTaskResponse,
    GetTaskRequest,
    GetTaskResponse,
    SendMessageRequest,
    SendMessageResponse,
    Task,
    TaskResult,
    TextPart,
)

from agentarea_tasks.domain.models import SimpleTask
from agentarea_tasks.task_service import TaskService

logger = logging.getLogger(__name__)


class A2ATaskBridge:
    """Bridge between A2A protocol and internal TaskService."""

    def __init__(self, task_service: TaskService):
        """Initialize with TaskService dependency."""
        self.task_service = task_service

    async def on_send_task(self, request: SendMessageRequest) -> SendMessageResponse:
        """Handle A2A task send request."""
        try:
            # Extract parameters from A2A request
            params = request.params
            task_id = params.id
            session_id = params.session_id
            message = params.message
            metadata = params.metadata or {}

            # Extract agent_id from metadata
            agent_id_str = metadata.get("agent_id")
            if not agent_id_str:
                raise ValueError("agent_id is required in metadata")

            agent_id = UUID(agent_id_str)

            # Extract text from message parts
            text_content = ""
            if message.parts:
                for part in message.parts:
                    if isinstance(part, TextPart):
                        text_content += part.text

            # Create internal task
            task = SimpleTask(
                title=f"A2A Task {task_id}",
                description=text_content,
                query=text_content,
                user_id=metadata.get("user_id", "a2a_user"),
                agent_id=agent_id,
                task_parameters={
                    "session_id": session_id,
                    "a2a_request": True,
                    "metadata": metadata,
                },
                status="submitted",
            )

            # Submit task through TaskService
            submitted_task = await self.task_service.submit_task(task)

            # Create A2A response
            task_result = TaskResult(
                id=str(submitted_task.id),
                status="submitted",
                message=f"Task {submitted_task.id} submitted successfully",
                session_id=session_id,
                artifacts=[],
                usage_metadata={},
            )

            return SendMessageResponse(
                id=request.id,
                result=task_result,
            )

        except Exception as e:
            logger.error(f"Error in A2A task send: {e}", exc_info=True)
            return SendMessageResponse(
                id=request.id,
                error={
                    "code": -32603,
                    "message": f"Internal error: {e!s}",
                    "data": None,
                },
            )

    async def on_get_task(self, request: GetTaskRequest) -> GetTaskResponse:
        """Handle A2A task get request."""
        try:
            task_id = UUID(request.params.id)

            # Get task from TaskService
            task = await self.task_service.get_task(task_id)

            if not task:
                return GetTaskResponse(
                    id=request.id,
                    error={
                        "code": -32602,
                        "message": f"Task {task_id} not found",
                        "data": None,
                    },
                )

            # Convert to A2A Task format
            a2a_task = Task(
                id=str(task.id),
                status=task.status,
                message=task.result.get("message", "") if task.result else "",
                session_id=task.task_parameters.get("session_id", ""),
                artifacts=task.result.get("artifacts", []) if task.result else [],
                usage_metadata=task.result.get("usage_metadata", {}) if task.result else {},
            )

            return GetTaskResponse(
                id=request.id,
                result=a2a_task,
            )

        except Exception as e:
            logger.error(f"Error in A2A task get: {e}", exc_info=True)
            return GetTaskResponse(
                id=request.id,
                error={
                    "code": -32603,
                    "message": f"Internal error: {e!s}",
                    "data": None,
                },
            )

    async def on_cancel_task(self, request: CancelTaskRequest) -> CancelTaskResponse:
        """Handle A2A task cancel request."""
        try:
            task_id = UUID(request.params.id)

            # Cancel task through TaskService
            success = await self.task_service.cancel_task(task_id)

            if success:
                return CancelTaskResponse(
                    id=request.id,
                    result={"cancelled": True, "task_id": str(task_id)},
                )
            else:
                return CancelTaskResponse(
                    id=request.id,
                    error={
                        "code": -32602,
                        "message": f"Failed to cancel task {task_id}",
                        "data": None,
                    },
                )

        except Exception as e:
            logger.error(f"Error in A2A task cancel: {e}", exc_info=True)
            return CancelTaskResponse(
                id=request.id,
                error={
                    "code": -32603,
                    "message": f"Internal error: {e!s}",
                    "data": None,
                },
            )
