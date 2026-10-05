"""Inbox API endpoints.

Surfaces tasks requiring user attention — filtered view over existing task state.
"""

import logging
from uuid import UUID

from agentarea_agents.application.agent_service import AgentService
from agentarea_api.api.deps.services import get_read_agent_service, get_read_task_service
from agentarea_api.api.v1.agents_tasks import TaskWithAgent
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.route_authz import unrestricted
from agentarea_common.base import ReadRepositoryFactoryDep
from agentarea_common.base.pagination import MAX_PAGE
from agentarea_common.utils.types import UtcDatetime
from agentarea_tasks.domain.statuses import INBOX_STATUSES, InboxStatus
from agentarea_tasks.infrastructure.repository import TaskEventRepository
from agentarea_tasks.task_service import TaskService
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inbox", tags=["inbox"])


class InboxResponse(BaseModel):
    items: list[TaskWithAgent]
    total: int
    page: int
    page_size: int


class ApprovalDecision(BaseModel):
    """One answered approval request, as the workflow recorded the answer."""

    escalation_id: str
    task_id: UUID
    agent_id: UUID | None = None
    # None when the agent no longer resolves; never a placeholder name.
    agent_name: str | None = None
    task_description: str | None = None
    tool_name: str | None = None
    # None for decisions recorded before the response carried its outcome.
    approved: bool | None = None
    # Principal id of whoever decided; GET /v1/principals resolves it.
    decided_by: str | None = None
    comment: str | None = None
    decided_at: UtcDatetime


class ApprovalDecisionsResponse(BaseModel):
    items: list[ApprovalDecision]
    total: int
    page: int
    page_size: int


@router.get(
    "/",
    response_model=InboxResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def get_inbox_items(
    user_context: UserContextDep,
    repository_factory: ReadRepositoryFactoryDep,
    status: InboxStatus | None = Query(None, description="Filter to a specific inbox status"),
    agent_id: UUID | None = Query(None, description="Filter by agent ID"),
    page: int = Query(1, ge=1, le=MAX_PAGE),
    page_size: int = Query(100, ge=1, le=1000),
    agent_service: AgentService = Depends(get_read_agent_service),
    task_service: TaskService = Depends(get_read_task_service),
) -> InboxResponse:
    """List tasks requiring user attention.

    Returns tasks with actionable statuses (waiting_for_approval, completed, failed),
    ordered by most recently updated first. Includes total count for badge/pagination.
    """
    try:
        query_statuses = [status] if status else list(INBOX_STATUSES)
        offset = (page - 1) * page_size

        # Sequential awaits: agent_service and task_service share one AsyncSession
        # via ReadRepositoryFactoryDep, and asyncpg forbids concurrent ops on a
        # single connection ("another operation is in progress").
        agents_result = await agent_service.list()
        tasks = await task_service.task_repository.list_by_statuses(
            statuses=query_statuses,
            agent_id=agent_id,
            limit=page_size,
            offset=offset,
        )
        total = await task_service.task_repository.count_by_statuses(
            statuses=query_statuses,
        )

        agent_map = {str(agent.id): agent.name for agent in agents_result}

        # For tasks waiting on human approval, surface the still-unanswered request
        # (escalation id + tool name) so the inbox UI can approve/reject inline. The
        # escalation id only lives in the task event stream.
        requests = await repository_factory.create_repository(
            TaskEventRepository
        ).unanswered_approval_requests(
            [task.id for task in tasks if task.status == "waiting_for_approval"]
        )

        items = []
        for task in tasks:
            request = requests.get(task.id)
            items.append(
                TaskWithAgent(
                    id=task.id,
                    agent_id=task.agent_id,
                    agent_name=agent_map.get(str(task.agent_id)),
                    description=task.description,
                    parameters=task.parameters,
                    status=task.status,
                    result=task.result,
                    created_at=task.created_at,
                    execution_id=task.execution_id,
                    total_cost=(
                        task.result.get("total_cost") if isinstance(task.result, dict) else None
                    ),
                    escalation_id=request.data.get("escalation_id") if request else None,
                    escalation_tool_name=request.data.get("tool_name") if request else None,
                )
            )

        return InboxResponse(items=items, total=total, page=page, page_size=page_size)
    except Exception as e:
        logger.error(f"Failed to get inbox items: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get(
    "/decisions",
    response_model=ApprovalDecisionsResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def list_approval_decisions(
    user_context: UserContextDep,
    repository_factory: ReadRepositoryFactoryDep,
    page: int = Query(1, ge=1, le=MAX_PAGE),
    page_size: int = Query(50, ge=1, le=200),
    agent_service: AgentService = Depends(get_read_agent_service),
) -> ApprovalDecisionsResponse:
    """Answered approval requests, newest first: who decided what, and when."""
    try:
        agents = await agent_service.list()
        decisions, total = await repository_factory.create_repository(
            TaskEventRepository
        ).approval_decisions(limit=page_size, offset=(page - 1) * page_size)
    except Exception as e:
        logger.error("Failed to list approval decisions", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from e

    agent_names = {str(agent.id): agent.name for agent in agents}
    items = [
        ApprovalDecision(
            escalation_id=str(event.data.get("escalation_id") or ""),
            task_id=event.task_id,
            agent_id=event.data.get("agent_id"),
            agent_name=agent_names.get(str(event.data.get("agent_id"))),
            task_description=description,
            tool_name=event.data.get("tool_name"),
            approved=event.data.get("approved"),
            decided_by=event.data.get("approved_by") or None,
            comment=event.data.get("comment") or None,
            decided_at=event.timestamp,
        )
        for event, description in decisions
    ]
    return ApprovalDecisionsResponse(items=items, total=total, page=page, page_size=page_size)
