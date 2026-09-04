"""InboxToolset — read tasks that need user attention."""

import json
from uuid import UUID

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset

from .base import platform_read_context

INBOX_STATUSES = ["waiting_for_approval", "waiting_for_input", "completed", "failed"]


@toolset(
    namespace="agentarea/inbox",
    display_name="Inbox",
    description="Inspect agent inbox messages awaiting human input.",
    category="platform",
    plane="operate",
)
class InboxToolset(Toolset):
    """List tasks awaiting user action (waiting_for_approval, waiting_for_input, completed, failed)."""

    @tool_method(effect="read")
    async def list(
        self,
        status: str = "",
        agent_id: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> str:
        """List inbox items, optionally filtered by status or agent."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, broker, _secret):
            from agentarea_tasks.task_service import TaskService

            from agentarea_api.api.deps.services import (
                _create_task_manager,
                get_temporal_workflow_service,
            )

            task_manager = await _create_task_manager(repo_factory)
            workflow_service = await get_temporal_workflow_service()
            service = TaskService(
                repository_factory=repo_factory,
                event_broker=broker,
                task_manager=task_manager,
                workflow_service=workflow_service,
            )

            statuses = [status] if status and status in INBOX_STATUSES else INBOX_STATUSES
            offset = max(page - 1, 0) * page_size

            tasks = await service.task_repository.list_by_statuses(
                statuses=statuses,
                agent_id=UUID(agent_id) if agent_id else None,
                limit=page_size,
                offset=offset,
            )
            total = await service.task_repository.count_by_statuses(statuses=statuses)
            items = [
                {
                    "id": str(t.id),
                    "agent_id": str(t.agent_id) if t.agent_id else None,
                    "description": t.description,
                    "status": t.status,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in tasks
            ]
            return json.dumps(
                {"items": items, "total": total, "page": page, "page_size": page_size},
                default=str,
            )
