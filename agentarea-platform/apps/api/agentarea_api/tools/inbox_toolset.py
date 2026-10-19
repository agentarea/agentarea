"""InboxToolset — read tasks and held tool calls that need user attention."""

import json
from typing import Annotated, Literal
from uuid import UUID

from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import unrestricted
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.workspaces.lookup import workspace_slug_for
from agentarea_governance.application.tool_call_approvals import ToolCallApprovalService
from agentarea_governance.domain.tool_call_approvals import ToolCallApprovalStatus
from agentarea_tasks.domain.statuses import INBOX_STATUSES, InboxStatus
from pydantic import BaseModel, Field

from ..api.v1.tool_call_approvals import approval_page_url
from .base import platform_read_context


class InboxItemOutput(BaseModel):
    id: str = Field(description="Run id; pass it to `runs_get` or the other runs tools.")
    agent_id: str | None = Field(description="Agent the run belongs to.")
    description: str = Field(description="What the run was asked to do.")
    status: str = Field(description="Run status, one of the inbox statuses.")
    created_at: str | None = Field(description="When the run was created, ISO 8601.")


class HeldToolCallOutput(BaseModel):
    id: str = Field(description="Tool call approval id.")
    connector: str = Field(description="Connector the held call targets.")
    tool: str = Field(description="Tool the held call invokes.")
    requested_by: str = Field(description="Id of whoever made the call.")
    client_name: str | None = Field(description="Client that made the call, when known.")
    url: str = Field(description="Page where an approver approves or rejects the call.")
    created_at: str = Field(description="When the call was held, ISO 8601.")
    expires_at: str = Field(description="Deadline to decide, ISO 8601.")


class InboxPage(BaseModel):
    items: list[InboxItemOutput] = Field(description="Runs on this page.")
    total: int = Field(description="Runs matching the filters across all pages.")
    page: int = Field(description="Page number returned, from 1.")
    page_size: int = Field(description="Runs per page.")
    tool_call_approvals: list[HeldToolCallOutput] = Field(
        description="Client tool calls waiting on a person's approval; empty unless status is "
        "empty or waiting_for_approval."
    )


@toolset(
    namespace="agentarea/inbox",
    display_name="Inbox",
    description="Inspect agent inbox messages awaiting human input.",
    category="platform",
    plane="operate",
)
class InboxToolset(Toolset):
    """List tasks awaiting user action (waiting_for_approval, waiting_for_input, completed, failed)."""

    open_world = False

    @tool_method(display_name="List inbox items", effect="read", output=InboxPage)
    @unrestricted("the caller's own inbox, as GET /v1/inbox serves it")
    async def list(
        self,
        status: Annotated[
            InboxStatus | Literal[""],
            Field(description="Only runs in this status; empty for every inbox status."),
        ] = "",
        agent_id: Annotated[
            str, Field(description="Only runs of this agent id, from `agents_list`; empty for any.")
        ] = "",
        page: Annotated[int, Field(description="Page number, from 1.")] = 1,
        page_size: Annotated[int, Field(description="Runs per page.")] = 50,
    ) -> str:
        """List inbox items, optionally filtered by status or agent.

        ``tool_call_approvals`` lists the client tool calls waiting on a
        person's approval, each with the link that person opens.
        """
        if status and status not in INBOX_STATUSES:
            raise ToolError(
                f"Unknown inbox status {status!r}; expected one of {list(INBOX_STATUSES)}"
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

            agent_uuid = UUID(agent_id) if agent_id else None
            tasks = await service.task_repository.list_by_statuses(
                statuses=statuses,
                agent_id=agent_uuid,
                limit=page_size,
                offset=offset,
            )
            total = await service.task_repository.count_by_statuses(
                statuses=statuses, agent_id=agent_uuid
            )
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
