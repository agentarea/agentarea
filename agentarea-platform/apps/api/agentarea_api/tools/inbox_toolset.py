"""InboxToolset — read tasks and held tool calls that need user attention."""

import json
from uuid import UUID

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import unrestricted
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.workspaces.lookup import workspace_slug_for
from agentarea_governance.application.tool_call_approvals import ToolCallApprovalService
from agentarea_governance.domain.tool_call_approvals import ToolCallApprovalStatus
from agentarea_tasks.domain.statuses import INBOX_STATUSES

from ..api.v1.tool_call_approvals import approval_page_url
from .base import platform_read_context


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
    @unrestricted("the caller's own inbox, as GET /v1/inbox serves it")
    async def list(
        self,
        status: str = "",
        agent_id: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> str:
        """List inbox items, optionally filtered by status or agent.

        ``tool_call_approvals`` lists the client tool calls waiting on a
        person's approval, each with the link that person opens.
        """
        if status and status not in INBOX_STATUSES:
            return json.dumps(
                {
                    "error": f"Unknown inbox status {status!r}; expected one of {list(INBOX_STATUSES)}"
                }
            )
        async with platform_read_context() as (_session, user_ctx, repo_factory, broker, _secret):
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

            statuses = [status] if status else list(INBOX_STATUSES)
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
            approvals = []
            if not status or status == "waiting_for_approval":
                held, _ = await ToolCallApprovalService(repo_factory).list(
                    status=ToolCallApprovalStatus.PENDING, limit=page_size
                )
                slug = None
                for approval in held:
                    slug = slug or user_ctx.workspace_slug
                    slug = slug or await workspace_slug_for(user_ctx.workspace_id)
                    approvals.append(
                        {
                            "id": approval.id,
                            "connector": approval.connector,
                            "tool": approval.tool,
                            "requested_by": approval.requested_by,
                            "client_name": approval.client_name,
                            "url": approval_page_url(slug, approval.id),
                            "created_at": approval.created_at.isoformat(),
                            "expires_at": approval.expires_at.isoformat(),
                        }
                    )
            return json.dumps(
                {
                    "items": items,
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "tool_call_approvals": approvals,
                },
                default=str,
            )
