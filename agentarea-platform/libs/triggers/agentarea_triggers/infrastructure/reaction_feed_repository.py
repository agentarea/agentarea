"""Reactions as the events feed reads them: a tally per event, and the tasks events started."""

from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from agentarea_streams.domain import ReactionTally, Verdict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .orm import TriggerExecutionORM


class ReactionFeedRepository(WorkspaceScopedRepository[TriggerExecutionORM]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, TriggerExecutionORM, user_context)

    async def tally(self, event_id: UUID) -> ReactionTally:
        # A batched reaction is still on its way: the event is processing until its batch fires.
        result = await self.session.execute(
            select(
                func.count().filter(
                    TriggerExecutionORM.verdict.is_distinct_from(Verdict.BATCHED.value)
                ),
                func.count().filter(TriggerExecutionORM.verdict == Verdict.SKIPPED.value),
                func.count().filter(TriggerExecutionORM.verdict == Verdict.ERROR.value),
            ).where(
                TriggerExecutionORM.event_id == event_id,
                TriggerExecutionORM.subscription_id.is_not(None),
                self._get_workspace_filter(),
            )
        )
        reacted, skipped, errors = result.one()
        return ReactionTally(reacted=reacted, skipped=skipped, errors=errors)

    async def list_for_event_ids(self, event_ids: list[UUID]) -> list[TriggerExecutionORM]:
        """The reactions to these events, whichever streams hold them."""
        if not event_ids:
            return []
        result = await self.session.execute(
            select(TriggerExecutionORM).where(
                TriggerExecutionORM.event_id.in_(event_ids),
                TriggerExecutionORM.subscription_id.is_not(None),
                self._get_workspace_filter(),
            )
        )
        return list(result.scalars().all())
