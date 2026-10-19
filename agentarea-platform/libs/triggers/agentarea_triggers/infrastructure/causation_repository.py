"""What the platform stream and its loop guard read of tasks and stream events, in one workspace."""

from uuid import UUID

from agentarea_streams.domain.platform import PlatformTask
from agentarea_streams.infrastructure.orm import StreamEventORM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..loop_guard import ChainEvent, ChainTask


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
