"""Agent delegation tool — delegates to another agent on the same platform.

Calls the task service directly (no HTTP, no A2A protocol overhead).
For external agents, use A2AAgentTool instead.
"""

import asyncio
import logging
import time
from typing import Any
from uuid import UUID, uuid4

from .a2a_agent_tool import _sanitize_tool_name
from .base_tool import BaseTool, ToolExecutionError

logger = logging.getLogger(__name__)

# Max time to wait for delegated task to complete (seconds)
DELEGATION_POLL_TIMEOUT = 120.0
DELEGATION_POLL_INTERVAL = 2.0


class AgentDelegationTool(BaseTool):
    """Tool that delegates a task to another agent on the same platform.

    Submits a task via the task service directly and polls for completion.
    No HTTP calls, no auth overhead — pure internal delegation.

    The task_service must have both submit_task() (to start execution) and
    get_task_with_workflow_status() (to poll for result).
    """

    def __init__(
        self,
        agent_name: str,
        agent_description: str,
        target_agent_id: UUID,
        task_service,
        workspace_id: str,
        user_id: str,
    ):
        self._agent_name = agent_name
        self._agent_description = agent_description
        self._target_agent_id = target_agent_id
        self._task_service = task_service
        self._workspace_id = workspace_id
        self._user_id = user_id

    @property
    def name(self) -> str:
        return _sanitize_tool_name(self._agent_name)

    @property
    def description(self) -> str:
        return f"Delegate a task to the '{self._agent_name}' agent. {self._agent_description}"

    def get_schema(self) -> dict[str, Any]:
        return {
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": (
                            f"The task or question to send to the '{self._agent_name}' agent. "
                            "Be specific and provide all necessary context."
                        ),
                    },
                },
                "required": ["message"],
            }
        }

    async def execute(self, **kwargs) -> dict[str, Any]:
        """Submit a task to the target agent and wait for completion."""
        message_text = kwargs.get("message", "")
        if not message_text:
            raise ToolExecutionError(self.name, "message is required")

        try:
            from agentarea_tasks.domain.models import SimpleTask

            task = SimpleTask(
                id=uuid4(),
                title=f"Delegated: {message_text[:80]}",
                description=f"Delegated from another agent to '{self._agent_name}'",
                query=message_text,
                user_id=self._user_id,
                workspace_id=self._workspace_id,
                agent_id=self._target_agent_id,
                status="submitted",
                task_parameters={},
                metadata={"source": "agent_delegation", "delegated": True},
            )

            created_task = await self._task_service.submit_task(task)
            task_id = created_task.id

            logger.info(
                f"Delegated task {task_id} to agent '{self._agent_name}' ({self._target_agent_id})"
            )

            # Poll for completion
            start_time = time.time()
            while time.time() - start_time < DELEGATION_POLL_TIMEOUT:
                updated_task = await self._task_service.get_task_with_workflow_status(task_id)
                if not updated_task:
                    raise ToolExecutionError(self.name, f"Task {task_id} disappeared")

                status = updated_task.status
                if status in ("completed", "failed", "cancelled"):
                    break

                await asyncio.sleep(DELEGATION_POLL_INTERVAL)
            else:
                return {
                    "success": False,
                    "result": f"Task {task_id} timed out after {DELEGATION_POLL_TIMEOUT}s",
                    "error": "timeout",
                    "tool_name": self.name,
                    "task_id": str(task_id),
                }

            if updated_task.status == "failed":
                error_msg = updated_task.result or "Task failed without details"
                return {
                    "success": False,
                    "result": error_msg,
                    "error": "task_failed",
                    "tool_name": self.name,
                    "task_id": str(task_id),
                }

            result_text = updated_task.result or "(No output from agent)"
            return {
                "success": True,
                "result": result_text,
                "error": None,
                "tool_name": self.name,
                "task_id": str(task_id),
                "task_state": updated_task.status,
            }

        except ToolExecutionError:
            raise
        except Exception as e:
            logger.error(f"Agent delegation failed: {e}")
            raise ToolExecutionError(self.name, str(e), e) from e


def create_task_service_for_delegation(session, user_context, event_broker):
    """Create a TaskService suitable for agent delegation.

    This is a helper for creating a TaskService inside Temporal activities
    where the full DI container isn't available.

    Args:
        session: Async database session
        user_context: UserContext with workspace_id
        event_broker: Event broker for publishing events

    Returns:
        TaskService with a TemporalTaskManager
    """
    from agentarea_common.base import RepositoryFactory
    from agentarea_tasks.infrastructure.repository import TaskRepository
    from agentarea_tasks.task_service import TaskService
    from agentarea_tasks.temporal_task_manager import TemporalTaskManager

    repository_factory = RepositoryFactory(session=session, user_context=user_context)
    task_repository = repository_factory.create_repository(TaskRepository)
    task_manager = TemporalTaskManager(task_repository=task_repository)

    return TaskService(
        repository_factory=repository_factory,
        event_broker=event_broker,
        task_manager=task_manager,
    )
