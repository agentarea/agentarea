"""Temporal-based task manager implementation for A2A protocol compliance.

This module provides a task manager that integrates with the existing execution
infrastructure without explicitly coupling to Temporal implementation details.
"""

import asyncio
import logging
from collections.abc import AsyncIterable
from typing import Any
from uuid import UUID, uuid4

from agentarea_agents.application.temporal_workflow_service import TemporalWorkflowService
from agentarea_agents.application.execution_service import ExecutionService
from agentarea_agents.infrastructure.temporal_orchestrator import TemporalWorkflowOrchestrator
from agentarea_common.config import get_settings
from a2a.types import (
    Artifact,
    CancelTaskRequest,
    CancelTaskResponse,
    GetTaskPushNotificationConfigRequest,
    GetTaskPushNotificationConfigResponse,
    GetTaskRequest,
    GetTaskResponse,
    InternalError,
    JSONRPCResponse,
    JSONRPCErrorResponse,
    Message,
    SendMessageRequest,
    SendMessageResponse,
    SendMessageSuccessResponse,
    SendStreamingMessageRequest,
    SendStreamingMessageResponse,
    SetTaskPushNotificationConfigRequest,
    SetTaskPushNotificationConfigResponse,
    Task,
    TaskIdParams,
    MessageSendParams,
    TaskQueryParams,
    TaskState,
    TaskStatus,
    TextPart,
    TaskNotFoundError,
    TaskResubscriptionRequest,
)

from .task_manager import BaseTaskManager

logger = logging.getLogger(__name__)


class TemporalTaskManager(BaseTaskManager):
    """Task manager implementation that bridges A2A protocol with workflow execution.

    This implementation uses the existing execution infrastructure to handle
    agent tasks via workflow orchestration while maintaining A2A compatibility.
    """

    def __init__(self):
        """Initialize the task manager with workflow service."""
        self._workflow_service = self._create_workflow_service()
        self._task_cache: dict[str, Task] = {}
        self._lock = asyncio.Lock()

    def _create_workflow_service(self) -> TemporalWorkflowService:
        """Create workflow service using existing infrastructure."""
        settings = get_settings()

        # Create the orchestrator using existing infrastructure
        orchestrator = TemporalWorkflowOrchestrator(
            temporal_address=settings.workflow.TEMPORAL_SERVER_URL,
            task_queue=settings.workflow.TEMPORAL_TASK_QUEUE,
            max_concurrent_activities=settings.workflow.TEMPORAL_MAX_CONCURRENT_ACTIVITIES,
            max_concurrent_workflows=settings.workflow.TEMPORAL_MAX_CONCURRENT_WORKFLOWS,
        )

        # Create execution service
        execution_service = ExecutionService(orchestrator)

        # Create workflow service
        return TemporalWorkflowService(execution_service)

    async def on_send_task(self, request: SendMessageRequest) -> SendMessageSuccessResponse:
        """Handle A2A message sending by starting workflow execution."""
        logger.info(f"Processing A2A message send: {request.params.message.taskId}")

        try:
            # Get task parameters
            task_params = request.params

            # Extract user message from the message parts
            user_message = ""
            for part in task_params.message.parts:
                if isinstance(part, TextPart):
                    user_message += part.text

            # Extract metadata from the message
            metadata = {
                "method": "tasks/send",
                "message_id": task_params.message.messageId,
                "context_id": task_params.message.contextId,
                "task_id": task_params.message.taskId,
                **(task_params.message.metadata or {}),
                **(task_params.metadata or {}),
            }

            # Get agent_id from metadata
            agent_id_str = metadata.get("agent_id")
            if not agent_id_str:
                raise ValueError("Agent ID is required in task metadata")

            agent_id = UUID(agent_id_str)

            # Start workflow execution
            workflow_result = await self._workflow_service.execute_agent_task_async(
                agent_id=agent_id,
                task_query=user_message,
                user_id=metadata.get("user_id", "a2a_user"),
                session_id=task_params.message.contextId or "default_session",
                task_parameters={
                    "a2a_request": True,
                    "method": metadata.get("method", "tasks/send"),
                    **metadata,
                },
                timeout_seconds=300,
            )

            # Create task from workflow result
            task = await self._create_task_from_workflow_result(
                task_params, workflow_result, agent_id
            )

            # Cache the task for later retrieval
            if task:
                self._task_cache[task.id] = task

            return SendMessageSuccessResponse(id=request.id, jsonrpc="2.0", result=task)

        except Exception as e:
            logger.error(f"Error in on_send_task: {e}", exc_info=True)
            from a2a.types import JSONRPCErrorResponse

            return JSONRPCErrorResponse(
                id=request.id, jsonrpc="2.0", error=InternalError(message=str(e))
            )

    async def on_get_task(self, request: GetTaskRequest) -> GetTaskResponse:
        """Handle A2A task retrieval by querying workflow status."""
        logger.info(f"Getting task: {request.params.id}")

        try:
            task_id = request.params.id

            # Check cache first
            async with self._lock:
                cached_task = self._task_cache.get(task_id)

            if cached_task:
                # Update task status from workflow
                updated_task = await self._update_task_from_workflow(cached_task)

                # Update cache
                async with self._lock:
                    self._task_cache[task_id] = updated_task

                return GetTaskResponse(id=request.id, result=updated_task)

            # If not in cache, task not found
            return GetTaskResponse(id=request.id, error=TaskNotFoundError())

        except Exception as e:
            logger.error(f"Error in on_get_task: {e}", exc_info=True)
            return GetTaskResponse(
                id=request.id, error=InternalError(message=f"Failed to get task: {e!s}")
            )

    async def on_cancel_task(self, request: CancelTaskRequest) -> CancelTaskResponse:
        """Handle A2A task cancellation by canceling workflow execution."""
        logger.info(f"Canceling task: {request.params.id}")

        try:
            task_id = request.params.id

            # Try to cancel the workflow
            execution_id = f"agent-task-{task_id}"
            success = await self._workflow_service.cancel_task(execution_id)

            if success:
                # Update cached task status
                async with self._lock:
                    if task_id in self._task_cache:
                        task = self._task_cache[task_id]
                        task.status.state = TaskState.CANCELED
                        self._task_cache[task_id] = task
                        return CancelTaskResponse(id=request.id, result=task)

                return CancelTaskResponse(id=request.id, result=None)
            else:
                return CancelTaskResponse(id=request.id, error=TaskNotFoundError())

        except Exception as e:
            logger.error(f"Error in on_cancel_task: {e}", exc_info=True)
            return CancelTaskResponse(
                id=request.id, error=InternalError(message=f"Failed to cancel task: {e!s}")
            )

    async def on_send_task_subscribe(
        self, request: SendStreamingMessageRequest
    ) -> AsyncIterable[SendStreamingMessageResponse] | JSONRPCResponse:
        """Handle A2A task streaming (not fully implemented)."""
        logger.info(f"Task streaming requested for: {request.params.id}")

        # For now, return the task result as a single event
        # In a full implementation, this would stream workflow progress
        send_response = await self.on_send_task(
            SendMessageRequest(id=request.id, params=request.params)
        )

        if send_response.error:
            return JSONRPCResponse(id=request.id, error=send_response.error)

        async def stream_task_result():
            # Create a task status update event from the task result
            if send_response.result:
                task_status_event = TaskStatusUpdateEvent(
                    id=send_response.result.id,
                    status=send_response.result.status,
                    final=send_response.result.status.state
                    in [TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED],
                    metadata=send_response.result.metadata,
                )
                yield SendStreamingMessageResponse(id=request.id, result=task_status_event)

        return stream_task_result()

    async def on_set_task_push_notification(
        self, request: SetTaskPushNotificationConfigRequest
    ) -> SetTaskPushNotificationConfigResponse:
        """Handle push notification setup (not implemented)."""
        logger.warning("Push notifications not implemented")
        return SetTaskPushNotificationConfigResponse(
            id=request.id, error=InternalError(message="Push notifications not implemented")
        )

    async def on_get_task_push_notification(
        self, request: GetTaskPushNotificationConfigRequest
    ) -> GetTaskPushNotificationConfigResponse:
        """Handle push notification retrieval (not implemented)."""
        logger.warning("Push notifications not implemented")
        return GetTaskPushNotificationConfigResponse(
            id=request.id, error=InternalError(message="Push notifications not implemented")
        )

    async def on_resubscribe_to_task(
        self, request: TaskResubscriptionRequest
    ) -> AsyncIterable[SendMessageResponse] | JSONRPCResponse:
        """Handle task resubscription (not implemented)."""
        logger.warning("Task resubscription not implemented")
        return JSONRPCResponse(
            id=request.id, error=InternalError(message="Task resubscription not implemented")
        )

    async def on_get_tasks_by_user(self, user_id: str) -> list[Task]:
        """Get tasks by user ID from cache."""
        async with self._lock:
            return [
                task
                for task in self._task_cache.values()
                if task.metadata and task.metadata.get("user_id") == user_id
            ]

    async def on_get_tasks_by_agent(self, agent_id: str) -> list[Task]:
        """Get tasks by agent ID from cache."""
        async with self._lock:
            return [
                task
                for task in self._task_cache.values()
                if task.metadata and task.metadata.get("agent_id") == agent_id
            ]

    # Helper methods for conversion between workflow and A2A formats

    def _extract_user_message(self, message: Message) -> str:
        """Extract user message content from A2A Message format."""
        if not message.parts:
            return ""

        # Get first text part
        for part in message.parts:
            if hasattr(part, "text") and part.text:
                return part.text
            elif hasattr(part, "type") and part.type == "text":
                return getattr(part, "text", "")

        return ""

    async def _create_task_from_workflow_result(
        self,
        task_params: MessageSendParams,
        workflow_result: dict[str, Any],
        agent_id: UUID,
    ) -> Task:
        """Create A2A Task from workflow execution result."""

        # Determine initial task state
        task_state = TaskState.SUBMITTED
        if workflow_result.get("success"):
            task_state = TaskState.WORKING  # Workflow started successfully
        elif workflow_result.get("error"):
            task_state = TaskState.FAILED

        # Create task status
        task_status = TaskStatus(
            state=task_state,
            message=None,  # Will be updated when workflow completes
        )

        # Create initial task
        task = Task(
            id=task_params.id,
            sessionId=task_params.sessionId,
            status=task_status,
            history=[task_params.message],
            artifacts=None,
            metadata={
                **task_params.metadata,
                "execution_id": workflow_result.get("execution_id"),
                "agent_id": str(agent_id),
                "workflow_started": True,
            },
        )

        return task

    async def _update_task_from_workflow(self, task: Task) -> Task:
        """Update task status from workflow execution."""
        try:
            execution_id = task.metadata.get("execution_id")
            if not execution_id:
                return task

            # Get workflow status
            workflow_status = await self._workflow_service.get_workflow_status(execution_id)

            # Update task based on workflow status
            updated_task = task.model_copy(deep=True)

            # Map workflow status to task state
            workflow_state = workflow_status.get("status", "unknown")
            if workflow_state == "completed":
                updated_task.status.state = TaskState.COMPLETED

                # Extract final response and create artifacts
                result = workflow_status.get("result", {})
                final_response = result.get("final_response", "Task completed")

                if final_response:
                    artifact = Artifact(
                        name="response",
                        parts=[TextPart(text=final_response)],
                        metadata={
                            "type": "final_response",
                            "success": result.get("success", True),
                        },
                    )

                    if updated_task.artifacts is None:
                        updated_task.artifacts = []
                    updated_task.artifacts.append(artifact)

            elif workflow_state == "failed":
                updated_task.status.state = TaskState.FAILED
                error_message = workflow_status.get("error", "Workflow failed")
                updated_task.status.message = error_message

            elif workflow_state == "running":
                updated_task.status.state = TaskState.WORKING

            elif workflow_state == "cancelled":
                updated_task.status.state = TaskState.CANCELLED

            return updated_task

        except Exception as e:
            logger.error(f"Error updating task from workflow: {e}")
            return task
