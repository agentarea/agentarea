"""A person's verdict on a run.

Only people rate runs: the API endpoint checks the principal and no toolset
exposes this, so an agent cannot grade itself or steer an experiment.
"""

from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_tasks.infrastructure.orm import TaskORM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_evals.models import RATINGS, RunFeedback


class UnknownRunError(LookupError):
    pass


class FeedbackService:
    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.user_context = user_context

    async def run(self, task_id: UUID) -> TaskORM:
        task = (
            await self.session.execute(
                select(TaskORM).where(
                    TaskORM.id == task_id, TaskORM.workspace_id == self.user_context.workspace_id
                )
            )
        ).scalar_one_or_none()
        if task is None:
            raise UnknownRunError(f"run {task_id} not found")
        return task

    async def rate(
        self, task_id: UUID, rating: str, *, comment: str | None, event_id: str | None
    ) -> RunFeedback:
        if rating not in RATINGS:
            raise ValueError(f"rating must be one of {RATINGS}, got {rating!r}")
        task = await self.run(task_id)

        existing = (
            await self.session.execute(
                select(RunFeedback).where(
                    RunFeedback.task_id == task_id,
                    RunFeedback.created_by == self.user_context.user_id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = RunFeedback(
                task_id=task_id,
                agent_id=task.agent_id,
                workspace_id=self.user_context.workspace_id,
                created_by=self.user_context.user_id,
                rating=rating,
            )
            self.session.add(existing)
        existing.rating = rating
        existing.comment = comment
        existing.event_id = event_id
        await self.session.commit()
        return existing

    async def list_for_task(self, task_id: UUID) -> list[RunFeedback]:
        result = await self.session.execute(
            select(RunFeedback)
            .where(
                RunFeedback.task_id == task_id,
                RunFeedback.workspace_id == self.user_context.workspace_id,
            )
            .order_by(RunFeedback.created_at)
        )
        return list(result.scalars().all())
