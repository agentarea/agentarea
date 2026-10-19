"""Inbox API endpoints.

Surfaces tasks requiring user attention — filtered view over existing task state.
"""

import asyncio
import logging
from typing import Any
from uuid import UUID

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.application.execution_service import WorkflowNotFoundError
from agentarea_agents.application.temporal_workflow_service import TemporalWorkflowService
from agentarea_api.api.deps.services import (
    get_read_agent_service,
    get_read_task_service,
    get_temporal_workflow_service,
)
from agentarea_api.api.v1.agents_tasks import TaskWithAgent
from agentarea_common.audit.repository import AuditRepository
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.route_authz import unrestricted
from agentarea_common.base import ReadRepositoryFactoryDep
from agentarea_common.base.pagination import MAX_PAGE
from agentarea_common.utils.types import UtcDatetime
from agentarea_execution.activities.agent.tool_audit import APPROVAL_APPROVED, APPROVAL_DENIED
from agentarea_tasks.domain.statuses import INBOX_STATUSES, InboxStatus
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.task_service import TaskService
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inbox", tags=["inbox"])

#: Workflow queries one inbox load has in flight at once.
ESCALATION_QUERY_CONCURRENCY = 8
#: Tasks per inbox page; each one waiting for approval costs a workflow query.
MAX_INBOX_PAGE_SIZE = 200


class InboxResponse(BaseModel):
    items: list[TaskWithAgent]
    total: int
    page: int
    page_size: int


class ApprovalDecision(BaseModel):
    """One answered approval request, as the audit trail recorded the answer."""

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


async def _latest_open_escalation(
    workflows: TemporalWorkflowService, task_id: UUID, slots: asyncio.Semaphore
) -> dict[str, Any] | None:
    """The newest escalation the task's workflow still holds open, or None.

    One workflow that cannot be read leaves its task without an escalation
    instead of failing the whole inbox.
    """
    try:
        async with slots:
            pending = await workflows.get_pending_escalations(f"task-{task_id}")
    except WorkflowNotFoundError:
        logger.warning("Task %s waits for approval but has no workflow", task_id)
        return None
    except Exception:
        logger.error("Failed to read pending escalations of task %s", task_id, exc_info=True)
        return None
    return pending[-1] if pending else None


@router.get(
    "/",
    response_model=InboxResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def get_inbox_items(
    user_context: UserContextDep,
    status: InboxStatus | None = Query(None, description="Filter to a specific inbox status"),
    agent_id: UUID | None = Query(None, description="Filter by agent ID"),
    page: int = Query(1, ge=1, le=MAX_PAGE),
    page_size: int = Query(100, ge=1, le=MAX_INBOX_PAGE_SIZE),
    agent_service: AgentService = Depends(get_read_agent_service),
    task_service: TaskService = Depends(get_read_task_service),
    workflows: TemporalWorkflowService = Depends(get_temporal_workflow_service),
) -> InboxResponse:
    """List tasks requiring user attention.

    Returns tasks with actionable statuses (waiting_for_approval, completed, failed),
    newest call for attention first: when an ended run ended, when a waiting task
    began to wait. Includes total count for badge/pagination.
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
            agent_id=agent_id,
        )

        agent_map = {str(agent.id): agent.name for agent in agents_result}

        # For tasks waiting on human approval, surface the escalation the workflow
        # still holds open (escalation id + tool name) so the inbox UI can
        # approve/reject inline.
        waiting = [task.id for task in tasks if task.status == "waiting_for_approval"]
        slots = asyncio.Semaphore(ESCALATION_QUERY_CONCURRENCY)
        open_escalations = dict(
            zip(
                waiting,
                await asyncio.gather(
                    *(_latest_open_escalation(workflows, task_id, slots) for task_id in waiting)
                ),
                strict=True,
            )
        )

        items = []
        for task in tasks:
            escalation = open_escalations.get(task.id)
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
                    escalation_id=escalation["escalation_id"] if escalation else None,
                    escalation_tool_name=escalation["tool_name"] if escalation else None,
                    provenance=task.provenance,
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
    """Answered approval requests, newest first: who decided what, and when.

    Read from the audit trail, where the tool audit records every decision.
    """
    try:
        agents = await agent_service.list()
        decisions, total = await AuditRepository(repository_factory.session).resource_events_page(
            user_context.workspace_id,
            resource_type="task",
            actions=(APPROVAL_APPROVED, APPROVAL_DENIED),
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        tasks = await repository_factory.create_repository(TaskRepository).list_all(
            ids={str(event.resource_id) for event in decisions}
        )
    except Exception as e:
        logger.error("Failed to list approval decisions", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from e

    agent_names = {str(agent.id): agent.name for agent in agents}
    descriptions = {str(task.id): task.description for task in tasks}
    items = []
    for event in decisions:
        metadata = event.event_metadata or {}
        agent_id = metadata.get("agent_id")
        items.append(
            ApprovalDecision(
                escalation_id=str(metadata.get("escalation_id") or ""),
                task_id=UUID(str(event.resource_id)),
                agent_id=agent_id,
                agent_name=agent_names.get(str(agent_id)),
                task_description=descriptions.get(str(event.resource_id)),
                tool_name=metadata.get("tool"),
                approved=event.action == APPROVAL_APPROVED,
                decided_by=event.actor_id if event.actor_type == "user" else None,
                comment=metadata.get("comment") or None,
                decided_at=event.created_at,
            )
        )
    return ApprovalDecisionsResponse(items=items, total=total, page=page, page_size=page_size)
