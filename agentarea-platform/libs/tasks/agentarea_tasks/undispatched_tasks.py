"""Tasks stored ``pending`` whose workflow never started, found and started.

A task is written before its workflow starts; a process that dies in between
leaves it ``pending`` with no execution. Trigger tasks are left to their
firing's redelivery, which composes the event message the row does not keep.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import unscoped, workspace_scope
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .infrastructure.orm import TaskORM
from .task_service import TaskService

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=2)
# Older than this, a run nobody saw start is no longer one to start unasked.
HORIZON = timedelta(days=1)
BATCH_SIZE = 100

TaskServiceFor = Callable[[AsyncSession, UserContext], TaskService]


@dataclass(frozen=True)
class UndispatchedTask:
    id: UUID
    workspace_id: str
    owner: str


async def find_undispatched_tasks(
    session: AsyncSession, *, now: datetime
) -> list[UndispatchedTask]:
    """Pending tasks with no execution, older than ``STALE_AFTER``; run inside ``unscoped``.

    ``now`` is naive, as ``created_at`` is stored.
    """
    rows = await session.execute(
        select(TaskORM.id, TaskORM.workspace_id, TaskORM.created_by)
        .where(
            TaskORM.status == "pending",
            TaskORM.execution_id.is_(None),
            TaskORM.created_at < now - STALE_AFTER,
            TaskORM.created_at >= now - HORIZON,
            or_(TaskORM.origin_type.is_(None), TaskORM.origin_type != "trigger"),
        )
        .order_by(TaskORM.created_at)
        .limit(BATCH_SIZE)
    )
    return [
        UndispatchedTask(id=r.id, workspace_id=r.workspace_id, owner=r.created_by) for r in rows
    ]


async def start_undispatched_tasks(
    session_factory: async_sessionmaker[AsyncSession],
    task_service_for: TaskServiceFor,
    *,
    now: datetime | None = None,
) -> int:
    """Start every undispatched task found; returns how many started.

    A task whose start fails stays ``pending`` and is tried again on the next run.
    """
    now = now or datetime.now()
    with unscoped("the reconciler finds tasks left unstarted in every workspace"):
        async with session_factory() as session:
            found = await find_undispatched_tasks(session, now=now)
    started = 0
    for candidate in found:
        with workspace_scope(candidate.workspace_id):
            async with session_factory() as session:
                service = task_service_for(
                    session,
                    UserContext(user_id=candidate.owner, workspace_id=candidate.workspace_id),
                )
                task = await service.get_task(candidate.id)
                if task is None or task.status != "pending" or task.execution_id:
                    continue
                try:
                    await service.restart_undispatched_task(task)
                except Exception:
                    logger.error(
                        "Task %s left pending with no workflow could not be started; retried next run",
                        candidate.id,
                        exc_info=True,
                    )
                    await session.rollback()
                    continue
                await session.commit()
                started += 1
                logger.info("Started task %s that was left pending with no workflow", task.id)
    return started
