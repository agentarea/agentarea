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
        total = await task_service.task_repository.count_by_statuses(
            statuses=query_statuses,
        )

        agent_map = {str(agent.id): agent.name for agent in agents_result}

        items = [
            TaskWithAgent(
                id=task.id,
                agent_id=task.agent_id,
                agent_name=agent_map.get(str(task.agent_id), "Unknown"),
                description=task.description,
                parameters=task.parameters,
                status=task.status,
                result=task.result,
                created_at=task.created_at,
                execution_id=task.execution_id,
                total_cost=(
                    task.result.get("total_cost") if isinstance(task.result, dict) else None
                ),
            )
            for task in tasks
        ]

        return InboxResponse(items=items, total=total, page=page, page_size=page_size)
    except Exception as e:
        logger.error(f"Failed to get inbox items: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from e
