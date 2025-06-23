"""
Database Task Manager

Real implementation of TaskManager that persists tasks in the database
instead of using in-memory storage.
"""

import logging
from collections.abc import AsyncIterable
from typing import Dict, Any, Optional, List
from uuid import uuid4
from datetime import datetime, timezone

from agentarea.common.utils.types import (
    SendTaskRequest,
    SendTaskResponse,
    SendTaskStreamingRequest,
    SendTaskStreamingResponse,
    GetTaskRequest,
    GetTaskResponse,
    CancelTaskRequest,
    CancelTaskResponse,
    SetTaskPushNotificationRequest,
    SetTaskPushNotificationResponse,
    GetTaskPushNotificationRequest,
    GetTaskPushNotificationResponse,
    TaskResubscriptionRequest,
    Task,
    TaskStatus,
    TaskState,
    Message,
    TextPart,
    JSONRPCError,
    JSONRPCResponse,
)
from agentarea.modules.tasks.task_manager import BaseTaskManager
from agentarea.modules.tasks.infrastructure.repository import TaskRepositoryInterface
from agentarea.modules.tasks.domain.models import Task as DomainTask, TaskType, TaskPriority
from agentarea.common.events.broker import EventBroker
from agentarea.modules.tasks.domain.events import TaskCreated, TaskStatusChanged, TaskCompleted

logger = logging.getLogger(__name__)


class DatabaseTaskManager(BaseTaskManager):
    """Database-backed task manager with real persistence."""

    def __init__(self, task_repository: TaskRepositoryInterface, event_broker: EventBroker):
        self.task_repository = task_repository
        self.event_broker = event_broker
        self.active_tasks: Dict[str, Task] = {}

    async def on_send_task(self, request: SendTaskRequest) -> SendTaskResponse:
        """Handle task sending with database persistence."""
        try:
            # Extract task parameters
            params = request.params
            task_id = getattr(params, "id", str(uuid4()))
            session_id = getattr(params, "sessionId", str(uuid4()))
            message = getattr(params, "message", None)
            metadata = getattr(params, "metadata", {}) or {}

            # Create domain task for database storage
            domain_task = DomainTask(
                id=task_id,
                description=self._extract_message_text(message),
                task_type=TaskType.SIMPLE,
                priority=TaskPriority.NORMAL,
                parameters={"message": message.model_dump() if message else {}},
                metadata=metadata,
                agent_id=metadata.get("agent_id"),
                created_by=metadata.get("user_id", "system"),
            )

            # Save to database
            saved_task = await self.task_repository.create(domain_task)
            logger.info(f"Created database task {saved_task.id}")

            # Create A2A protocol task
            a2a_task = Task(
                id=task_id,
                sessionId=session_id,
                status=TaskStatus(
                    state=TaskState.SUBMITTED,
                    message=Message(
                        role="agent", parts=[TextPart(text="Task queued for processing")]
                    ),
                ),
                metadata=metadata,
            )

            # Store in active tasks
            self.active_tasks[task_id] = a2a_task

            # Publish task created event
            await self.event_broker.publish(
                TaskCreated(
                    task_id=task_id,
                    agent_id=metadata.get("agent_id"),
                    description=domain_task.description,
                    parameters=domain_task.parameters,
                    metadata=metadata,
                )
            )

            return SendTaskResponse(id=request.id, result=a2a_task)

        except Exception as e:
            logger.error(f"Error creating task: {e}", exc_info=True)
            error = JSONRPCError(code=-32603, message="Internal error", data={"error": str(e)})
            return SendTaskResponse(id=request.id, error=error)

    async def on_send_task_subscribe(
        self, request: SendTaskStreamingRequest
    ) -> AsyncIterable[SendTaskStreamingResponse] | JSONRPCResponse:
        """Handle task subscription with database persistence."""
        try:
            # For streaming, create task first
            send_response = await self.on_send_task(
                SendTaskRequest(
                    id=request.id,
                    method=request.method.replace("Subscribe", ""),
                    params=request.params,
                )
            )

            if send_response.error:
                return JSONRPCResponse(id=request.id, error=send_response.error)

            # Yield streaming responses
            async def stream_generator():
                task = send_response.result
                if task:
                    # Simulate streaming updates
                    yield SendTaskStreamingResponse(
                        id=request.id,
                        result=None,  # Would contain actual streaming data
                    )

            return stream_generator()

        except Exception as e:
            logger.error(f"Error in streaming task: {e}", exc_info=True)
            return JSONRPCResponse(
                id=request.id,
                error=JSONRPCError(code=-32603, message="Internal error", data={"error": str(e)}),
            )

    async def on_get_task(self, request: GetTaskRequest) -> GetTaskResponse:
        """Get task status from database."""
        try:
            task_id = request.params.id

            # Check active tasks first
            if task_id in self.active_tasks:
                task = self.active_tasks[task_id]
                return GetTaskResponse(id=request.id, result=task)

            # Check database
            domain_task = await self.task_repository.get_by_id(task_id)
            if not domain_task:
                error = JSONRPCError(
                    code=-32001, message="Task not found", data={"task_id": task_id}
                )
                return GetTaskResponse(id=request.id, error=error)

            # Convert domain task to A2A task
            a2a_task = self._domain_to_a2a_task(domain_task)
            self.active_tasks[task_id] = a2a_task

            return GetTaskResponse(id=request.id, result=a2a_task)

        except Exception as e:
            logger.error(f"Error getting task {request.params.id}: {e}", exc_info=True)
            error = JSONRPCError(code=-32603, message="Internal error", data={"error": str(e)})
            return GetTaskResponse(id=request.id, error=error)

    async def on_cancel_task(self, request: CancelTaskRequest) -> CancelTaskResponse:
        """Cancel task in database."""
        try:
            task_id = request.params.id

            # Update in database
            domain_task = await self.task_repository.get_by_id(task_id)
            if not domain_task:
                error = JSONRPCError(
                    code=-32001, message="Task not found", data={"task_id": task_id}
                )
                return CancelTaskResponse(id=request.id, error=error)

            # Update task status
            domain_task.cancel("User requested cancellation")
            await self.task_repository.update(domain_task)

            # Update A2A task
            if task_id in self.active_tasks:
                a2a_task = self.active_tasks[task_id]
                a2a_task.status = TaskStatus(
                    state=TaskState.CANCELED,
                    message=Message(role="agent", parts=[TextPart(text="Task cancelled by user")]),
                )
            else:
                a2a_task = self._domain_to_a2a_task(domain_task)
                self.active_tasks[task_id] = a2a_task

            # Publish status change event
            await self.event_broker.publish(
                TaskStatusChanged(task_id=task_id, old_status="running", new_status="cancelled")
            )

            return CancelTaskResponse(id=request.id, result=a2a_task)

        except Exception as e:
            logger.error(f"Error cancelling task {request.params.id}: {e}", exc_info=True)
            error = JSONRPCError(code=-32603, message="Internal error", data={"error": str(e)})
            return CancelTaskResponse(id=request.id, error=error)

    async def on_set_task_push_notification(
        self, request: SetTaskPushNotificationRequest
    ) -> SetTaskPushNotificationResponse:
        """Set push notification configuration for a task."""
        try:
            # For now, just return the configuration back
            return SetTaskPushNotificationResponse(id=request.id, result=request.params)
        except Exception as e:
            logger.error(f"Error setting push notification: {e}", exc_info=True)
            return SetTaskPushNotificationResponse(
                id=request.id,
                error=JSONRPCError(code=-32603, message="Internal error", data={"error": str(e)}),
            )

    async def on_get_task_push_notification(
        self, request: GetTaskPushNotificationRequest
    ) -> GetTaskPushNotificationResponse:
        """Get push notification configuration for a task."""
        try:
            # For now, return empty configuration
            return GetTaskPushNotificationResponse(
                id=request.id,
                result=None,  # No push notification configured
            )
        except Exception as e:
            logger.error(f"Error getting push notification: {e}", exc_info=True)
            return GetTaskPushNotificationResponse(
                id=request.id,
                error=JSONRPCError(code=-32603, message="Internal error", data={"error": str(e)}),
            )

    async def on_resubscribe_to_task(
        self, request: TaskResubscriptionRequest
    ) -> AsyncIterable[SendTaskResponse] | JSONRPCResponse:
        """Resubscribe to task updates."""
        try:
            task_id = request.params.id

            # Get current task
            if task_id in self.active_tasks:
                task = self.active_tasks[task_id]

                async def resubscribe_generator():
                    yield SendTaskResponse(id=request.id, result=task)

                return resubscribe_generator()
            else:
                return JSONRPCResponse(
                    id=request.id, error=JSONRPCError(code=-32001, message="Task not found")
                )

        except Exception as e:
            logger.error(f"Error resubscribing to task: {e}", exc_info=True)
            return JSONRPCResponse(
                id=request.id,
                error=JSONRPCError(code=-32603, message="Internal error", data={"error": str(e)}),
            )

    # Extended querying capabilities
    async def on_get_tasks_by_user(self, user_id: str) -> List[Task]:
        """Get all tasks for a user."""
        try:
            # Get from database
            domain_tasks = await self.task_repository.get_by_filter({"created_by": user_id})

            # Convert to A2A tasks
            tasks = []
            for domain_task in domain_tasks:
                a2a_task = self._domain_to_a2a_task(domain_task)
                tasks.append(a2a_task)
                self.active_tasks[a2a_task.id] = a2a_task

            return tasks

        except Exception as e:
            logger.error(f"Error getting tasks for user {user_id}: {e}", exc_info=True)
            return []

    async def on_get_tasks_by_agent(self, agent_id: str) -> List[Task]:
        """Get all tasks for an agent."""
        try:
            # Get from database
            domain_tasks = await self.task_repository.get_by_filter({"agent_id": agent_id})

            # Convert to A2A tasks
            tasks = []
            for domain_task in domain_tasks:
                a2a_task = self._domain_to_a2a_task(domain_task)
                tasks.append(a2a_task)
                self.active_tasks[a2a_task.id] = a2a_task

            return tasks

        except Exception as e:
            logger.error(f"Error getting tasks for agent {agent_id}: {e}", exc_info=True)
            return []

    def _extract_message_text(self, message: Optional[Message]) -> str:
        """Extract text content from message."""
        if not message or not message.parts:
            return "No message content"

        text_parts = [part.text for part in message.parts if hasattr(part, "text")]
        return " ".join(text_parts) if text_parts else "No text content"

    def _domain_to_a2a_task(self, domain_task: DomainTask) -> Task:
        """Convert domain task to A2A protocol task."""
        # Map domain task status to A2A state
        state_mapping = {
            "pending": TaskState.SUBMITTED,
            "running": TaskState.WORKING,
            "completed": TaskState.COMPLETED,
            "failed": TaskState.FAILED,
            "cancelled": TaskState.CANCELED,
        }

        return Task(
            id=domain_task.id,
            sessionId=str(domain_task.id),  # Use task ID as session ID for now
            status=TaskStatus(
                state=state_mapping.get(domain_task.status.state, TaskState.SUBMITTED),
                message=Message(
                    role="agent",
                    parts=[TextPart(text=domain_task.status.message or "Task in progress")],
                ),
            ),
            metadata=domain_task.metadata or {},
        )
