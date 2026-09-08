"""Inbox API endpoints.

Surfaces tasks requiring user attention — filtered view over existing task state.
"""

import logging
from uuid import UUID

from agentarea_agents.application.agent_service import AgentService
from agentarea_api.api.deps.services import get_read_agent_service, get_read_task_service
from agentarea_api.api.v1.agents_tasks import TaskWithAgent
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_tasks.task_service import TaskService
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import bindparam, text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inbox", tags=["inbox"])

INBOX_STATUSES = [
    "waiting_for_approval",
    "waiting_for_input",
    "completed",
    "failed",
]


class InboxResponse(BaseModel):
    items: list[TaskWithAgent]
    total: int
    page: int
    page_size: int
    # Per-status totals across the whole workspace (independent of pagination),
    # so the UI can show accurate segment counts without loading every page.
    status_counts: dict[str, int] = {}


async def _pending_escalations_for_tasks(
    task_service: TaskService,
    task_ids: list,
) -> dict[str, dict]:
    """Resolve the latest unresolved approval escalation for each task.

    Reads the ``task_events`` stream — where escalation ids are emitted — and returns
    ``{task_id: {"escalation_id": ..., "tool_name": ...}}`` for the most recent
    HumanApprovalRequested event that has no matching Received/Denied event.
    """
    if not task_ids:
        return {}

    stmt = text(
        """
        SELECT DISTINCT ON (te.task_id)
               te.task_id::text          AS task_id,
               te.data->>'escalation_id' AS escalation_id,
               te.data->>'tool_name'     AS tool_name
        FROM task_events te
        WHERE te.task_id IN :task_ids
          AND te.event_type = 'HumanApprovalRequested'
          AND (te.data->>'escalation_id') NOT IN (
              SELECT r.data->>'escalation_id'
              FROM task_events r
              WHERE r.task_id = te.task_id
                AND r.event_type IN ('HumanApprovalReceived', 'HumanApprovalDenied')
                AND r.data->>'escalation_id' IS NOT NULL
          )
        ORDER BY te.task_id, te.timestamp DESC
        """
    ).bindparams(bindparam("task_ids", expanding=True))

    result = await task_service.task_repository.session.execute(
        stmt, {"task_ids": [str(tid) for tid in task_ids]}
    )
    return {
        row.task_id: {"escalation_id": row.escalation_id, "tool_name": row.tool_name}
        for row in result.fetchall()
    }


@router.get("/", response_model=InboxResponse)
async def get_inbox_items(
    user_context: UserContextDep,
    status: str | None = Query(None, description="Filter to a specific inbox status"),
    agent_id: UUID | None = Query(None, description="Filter by agent ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
    agent_service: AgentService = Depends(get_read_agent_service),
    task_service: TaskService = Depends(get_read_task_service),
) -> InboxResponse:
    """List tasks requiring user attention.

    Returns tasks with actionable statuses (waiting_for_approval, completed, failed),
    ordered by most recently updated first. Includes total count for badge/pagination.
    """
    try:
        query_statuses = [status] if status and status in INBOX_STATUSES else INBOX_STATUSES
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
        status_counts = await task_service.task_repository.count_grouped_by_statuses(
            statuses=query_statuses,
        )
        total = sum(status_counts.values())

        agent_map = {str(agent.id): agent.name for agent in agents_result}

        # For tasks waiting on human approval, surface the still-unresolved escalation
        # (id + tool name) so the inbox UI can approve/reject inline. The escalation id
        # only lives in the task_events stream, so resolve it in a single batch query.
        escalation_map = await _pending_escalations_for_tasks(
            task_service,
            [task.id for task in tasks if task.status == "waiting_for_approval"],
        )

        items = []
        for task in tasks:
            escalation = escalation_map.get(str(task.id), {})
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
                    escalation_id=escalation.get("escalation_id"),
                    escalation_tool_name=escalation.get("tool_name"),
                )
            )

        return InboxResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            status_counts=status_counts,
        )
    except Exception as e:
        logger.error(f"Failed to get inbox items: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from e
