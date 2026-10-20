"""What the platform stream and its loop guard read of tasks and stream events, in one workspace."""

import logging
from dataclasses import dataclass
from uuid import UUID

from agentarea_streams.domain.platform import PlatformTask
from agentarea_streams.infrastructure.orm import StreamEventORM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..loop_guard import ChainEvent, ChainTask

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TriggerOrigin:
    """The trigger a task was started by, and the task's owner."""

    trigger_id: UUID
    owner: str


async def load_platform_task(
    session: AsyncSession, task_id: UUID, workspace_id: str
) -> PlatformTask | None:
    from agentarea_tasks.infrastructure.orm import TaskORM

    row = (
        await session.execute(
            select(
                TaskORM.id,
                TaskORM.agent_id,
                TaskORM.created_by,
                TaskORM.correlation_id,
                TaskORM.depth,
            ).where(TaskORM.id == task_id, TaskORM.workspace_id == workspace_id)
        )
    ).one_or_none()
    if row is None:
        return None
    return PlatformTask(
        id=row.id,
        agent_id=row.agent_id,
        owner=row.created_by,
        correlation_id=row.correlation_id,
        depth=row.depth,
    )


async def load_trigger_origin(
    session: AsyncSession, task_id: UUID, workspace_id: str
) -> TriggerOrigin | None:
    """The trigger that started the task; None for a task nothing fired."""
    from agentarea_tasks.infrastructure.orm import TaskORM

    row = (
        await session.execute(
            select(TaskORM.origin_type, TaskORM.origin_id, TaskORM.created_by).where(
                TaskORM.id == task_id, TaskORM.workspace_id == workspace_id
            )
        )
    ).one_or_none()
    if row is None or row.origin_type != "trigger" or not row.origin_id:
        return None
    try:
        trigger_id = UUID(row.origin_id)
    except ValueError:
        logger.exception("Task %s names a trigger origin that is no id: %r", task_id, row.origin_id)
        return None
    return TriggerOrigin(trigger_id=trigger_id, owner=row.created_by)


class StoredCausationChain:
    """The chain as the tasks table and the events read model hold it, in one workspace."""

    def __init__(self, session: AsyncSession, workspace_id: str):
        self._session = session
        self._workspace_id = workspace_id

    async def task(self, task_id: UUID) -> ChainTask | None:
        from agentarea_tasks.infrastructure.orm import TaskORM

        row = (
            await self._session.execute(
                select(TaskORM.origin_type, TaskORM.origin_id, TaskORM.causation_id).where(
                    TaskORM.id == task_id, TaskORM.workspace_id == self._workspace_id
                )
            )
        ).one_or_none()
        if row is None:
            return None
        return ChainTask(
            origin_type=row.origin_type, origin_id=row.origin_id, causation_id=row.causation_id
        )

    async def event(self, event_id: UUID) -> ChainEvent | None:
        row = (
            await self._session.execute(
                select(StreamEventORM.source_type, StreamEventORM.subject)
                .where(
                    StreamEventORM.event_id == event_id,
                    StreamEventORM.workspace_id == self._workspace_id,
                )
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            return None
        return ChainEvent(source_type=row.source_type, subject=row.subject)
