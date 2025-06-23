"""A2A-Native Chat Extensions.

This module provides chat functionality using pure A2A Task protocol.
No custom session management - everything uses A2A Tasks with contextId for conversations.
"""

import logging
from collections.abc import AsyncIterable
from datetime import UTC, datetime
from uuid import uuid4

from agentarea.common.utils.types import (
    Message,
    SendTaskRequest,
    SendTaskStreamingRequest,
    SendTaskStreamingResponse,
    Task,
    TaskSendParams,
    TaskState,
    TextPart,
)
from agentarea.modules.agents.application.agent_service import AgentService
from agentarea.modules.tasks.task_manager import BaseTaskManager

logger = logging.getLogger(__name__)


class A2AChatService:
    """A2A-compliant chat service using pure Task protocol.

    Uses A2A concepts:
    - Task.id: Unique identifier for each message/response cycle
    - Task.contextId: Groups related conversations
    - Task.history: Maintains full conversation automatically
    - Task.status: Tracks message processing (submitted → working → completed)
    - Task.artifacts: Contains agent responses
    - Task.metadata: Stores user_id, agent_id, etc.
    """

    def __init__(self, task_manager: BaseTaskManager, agent_service: AgentService):
        self.task_manager = task_manager
        self.agent_service = agent_service

    async def send_chat_message(
        self, agent_id: str, user_id: str, message_text: str, context_id: str | None = None
    ) -> Task:
        """Send a chat message to an agent using A2A protocol.

        Args:
            agent_id: Target agent ID
            user_id: User sending the message
            message_text: The chat message content
            context_id: Optional context to continue existing conversation

        Returns:
            Task: A2A Task object representing the chat interaction
        """
        try:
            # Generate unique IDs for this interaction
            task_id = str(uuid4())
            if not context_id:
                context_id = str(uuid4())  # New conversation

            # Create A2A Message
            user_message = Message(role="user", parts=[TextPart(text=message_text)])

            # Create A2A TaskSendParams
            task_params = TaskSendParams(
                id=task_id,
                sessionId=context_id,  # A2A uses sessionId for grouping
                message=user_message,
                metadata={
                    "user_id": user_id,
                    "agent_id": agent_id,
                    "chat_message": True,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

            # Send via A2A protocol
            request = SendTaskRequest(id=str(uuid4()), params=task_params)

            response = await self.task_manager.on_send_task(request)

            if response.error:
                logger.error(f"A2A task failed: {response.error}")
                raise Exception(f"Chat message failed: {response.error}")

            if response.result is None:
                raise Exception("Task creation returned None result")

            logger.info(
                f"Chat message sent successfully. Task ID: {task_id}, Context: {context_id}"
            )
            return response.result

        except Exception as e:
            logger.error(f"Failed to send chat message: {e}", exc_info=True)
            raise

    async def get_conversation_history(
        self, context_id: str, limit: int | None = None
    ) -> list[Task]:
        """Get conversation history for a context using A2A protocol.

        Args:
            context_id: The conversation context ID (sessionId in A2A)
            limit: Optional limit on number of tasks returned

        Returns:
            List[Task]: All tasks in the conversation, ordered by creation time
        """
        try:
            # Use existing task manager methods to get tasks by session/context
            # This assumes the task manager can filter by sessionId/contextId

            # Get all tasks and filter by contextId/sessionId
            # Note: This is a simplified approach - in production you'd want
            # proper database queries for efficiency
            user_tasks = await self.task_manager.on_get_tasks_by_user("all")  # Get all tasks

            conversation_tasks = [
                task
                for task in user_tasks
                if task.metadata
                and task.metadata.get("chat_message")
                and (
                    getattr(task, "sessionId", None) == context_id
                    or getattr(task, "contextId", None) == context_id
                )
            ]

            # Sort by task ID (since A2A Tasks don't have created_at timestamp)
            # Task IDs are UUIDs generated in chronological order
            conversation_tasks.sort(key=lambda t: t.id)

            if limit:
                conversation_tasks = conversation_tasks[-limit:]  # Get latest N tasks

            logger.info(f"Retrieved {len(conversation_tasks)} tasks for context {context_id}")
            return conversation_tasks

        except Exception as e:
            logger.error(f"Failed to get conversation history: {e}", exc_info=True)
            raise

    async def get_user_conversations(self, user_id: str) -> list[str]:
        """Get list of conversation context IDs for a user.

        Args:
            user_id: The user ID

        Returns:
            List[str]: List of context IDs (sessionIds) for user's conversations
        """
        try:
            # Get all tasks for user
            user_tasks = await self.task_manager.on_get_tasks_by_user(user_id)

            # Extract unique context IDs from chat messages
            context_ids: set[str] = set()
            for task in user_tasks:
                if (
                    task.metadata
                    and task.metadata.get("chat_message")
                    and task.metadata.get("user_id") == user_id
                ):
                    # Try sessionId for A2A Task compatibility
                    session_id = task.sessionId
                    if session_id:
                        context_ids.add(session_id)

            logger.info(f"Found {len(context_ids)} conversations for user {user_id}")
            return list(context_ids)

        except Exception as e:
            logger.error(f"Failed to get user conversations: {e}", exc_info=True)
            raise

    async def stream_chat_response(self, task_id: str) -> AsyncIterable[SendTaskStreamingResponse]:
        """Stream real-time updates for a chat task using A2A SSE protocol.

        Args:
            task_id: The task ID to stream updates for

        Yields:
            SendTaskStreamingResponse: A2A-compliant streaming responses
        """
        try:
            # Create streaming request for the task
            stream_request = SendTaskStreamingRequest(
                id=str(uuid4()),
                params=TaskSendParams(
                    id=task_id,
                    message=Message(role="user", parts=[]),  # Empty message for streaming
                ),
            )

            # Subscribe to task updates via A2A streaming protocol
            async for response in self.task_manager.on_send_task_subscribe(stream_request):
                if isinstance(response, SendTaskStreamingResponse):
                    yield response
                else:
                    # Handle JSONRPCResponse errors
                    logger.error(f"Streaming error: {response}")
                    break

        except Exception as e:
            logger.error(f"Failed to stream chat response: {e}", exc_info=True)
            raise

    async def get_active_chat_tasks(self, agent_id: str) -> list[Task]:
        """Get currently active (non-terminal) chat tasks for an agent.

        Args:
            agent_id: The agent ID

        Returns:
            List[Task]: Active chat tasks
        """
        try:
            agent_tasks = await self.task_manager.on_get_tasks_by_agent(agent_id)

            active_chat_tasks = [
                task
                for task in agent_tasks
                if (
                    task.metadata
                    and task.metadata.get("chat_message")
                    and task.status.state
                    not in [TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED]
                )
            ]

            logger.info(f"Found {len(active_chat_tasks)} active chat tasks for agent {agent_id}")
            return active_chat_tasks

        except Exception as e:
            logger.error(f"Failed to get active chat tasks: {e}", exc_info=True)
            raise

    async def cancel_chat_task(self, task_id: str) -> Task:
        """Cancel a chat task using A2A protocol.

        Args:
            task_id: The task ID to cancel

        Returns:
            Task: Updated task with canceled status
        """
        from agentarea.common.utils.types import CancelTaskRequest, TaskIdParams

        cancel_request = CancelTaskRequest(id=str(uuid4()), params=TaskIdParams(id=task_id))

        response = await self.task_manager.on_cancel_task(cancel_request)

        if response.error:
            logger.error(f"Failed to cancel task: {response.error}")
            raise Exception(f"Task cancellation failed: {response.error}")

        logger.info(f"Successfully canceled chat task {task_id}")
        return response.result


class A2AChatTaskManager:
    """Extension to BaseTaskManager specifically for chat functionality.

    Provides chat-specific convenience methods while maintaining A2A compliance.
    """

    def __init__(self, base_task_manager: BaseTaskManager):
        self.base_manager = base_task_manager

    async def get_tasks_by_context(self, context_id: str) -> list[Task]:
        """Get all tasks for a specific conversation context."""
        # This would ideally be implemented in the base task manager
        # For now, we'll filter from all tasks (inefficient but functional)
        all_tasks = []
        # Implementation depends on available methods in base_task_manager
        return [task for task in all_tasks if getattr(task, "sessionId", None) == context_id]

    async def get_chat_contexts_for_user(self, user_id: str) -> list[str]:
        """Get all conversation contexts for a user."""
        user_tasks = await self.base_manager.on_get_tasks_by_user(user_id)
        contexts = set()

        for task in user_tasks:
            if task.metadata and task.metadata.get("chat_message"):
                session_id = getattr(task, "sessionId", None)
                if session_id:
                    contexts.add(session_id)

        return list(contexts)
