"""The reactions of events held in a trigger's open batch, and their settling when it fires.

An event that joins a batch is recorded ``batched`` with the batch workflow's
id. Settling turns every held reaction of the batch into the batch's verdict,
with its task; a reaction already settled keeps what it says, so an event that
reached two batches is answered by the first.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_streams.domain import HandlerResult, Verdict
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..domain.enums import ExecutionStatus
from .orm import TriggerExecutionORM
from .reactions import ReactionRepository, StreamCause

_UNIQUE = "uq_trigger_executions_subscription_event"
_STATUS = {
    Verdict.REACTED: ExecutionStatus.SUCCESS,
    Verdict.SKIPPED: ExecutionStatus.SKIPPED,
    Verdict.ERROR: ExecutionStatus.FAILED,
}


class BatchReactionRepository(ReactionRepository):
    async def unsettled(self, subscription_id: UUID, event_ids: list[UUID]) -> list[UUID]:
        """The events of a batch still to settle: held, or not recorded yet, in batch order."""
        if not event_ids:
            return []
        result = await self.session.execute(
            select(TriggerExecutionORM.event_id).where(
                TriggerExecutionORM.subscription_id == subscription_id,
                TriggerExecutionORM.event_id.in_(event_ids),
                TriggerExecutionORM.verdict.is_distinct_from(Verdict.BATCHED.value),
                self._get_workspace_filter(),
            )
        )
        settled = set(result.scalars().all())
        return [e for e in event_ids if e not in settled]

    async def settle(
        self, causes: list[StreamCause], result: HandlerResult, *, workflow_id: str, now: datetime
    ) -> None:
        if result.verdict is Verdict.BATCHED:
            raise ValueError("a batch settles its events with a final verdict")
        for cause in causes:
            values: dict[str, Any] = {
                "status": _STATUS[result.verdict].value,
                "verdict": result.verdict.value,
                "reason": result.reason,
                "error_message": result.reason if result.verdict is Verdict.ERROR else None,
                "task_id": result.task_id,
                "workflow_id": workflow_id,
            }
            statement = pg_insert(TriggerExecutionORM).values(**self._row(cause, values, now))
            await self.session.execute(
                statement.on_conflict_do_update(
                    constraint=_UNIQUE,
                    set_={**values, "updated_at": now},
                    where=TriggerExecutionORM.verdict == Verdict.BATCHED.value,
                )
            )

    async def held_by_trigger(self, trigger_id: UUID) -> list[TriggerExecutionORM]:
        result = await self.session.execute(
            select(TriggerExecutionORM).where(
                TriggerExecutionORM.trigger_id == trigger_id,
                TriggerExecutionORM.verdict == Verdict.BATCHED.value,
                self._get_workspace_filter(),
            )
        )
        return list(result.scalars().all())

    async def skip_held(self, trigger_id: UUID, reason: str, *, now: datetime) -> None:
        await self.session.execute(
            update(TriggerExecutionORM)
            .where(
                TriggerExecutionORM.trigger_id == trigger_id,
                TriggerExecutionORM.verdict == Verdict.BATCHED.value,
                self._get_workspace_filter(),
            )
            .values(
                status=ExecutionStatus.SKIPPED.value,
                verdict=Verdict.SKIPPED.value,
                reason=reason,
                updated_at=now,
            )
        )
