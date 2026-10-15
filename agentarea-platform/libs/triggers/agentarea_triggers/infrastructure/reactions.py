"""One firing log: a stream subscription's reaction to a bus event is a trigger_executions row.

The row is unique per (subscription, event). The router records it before it
acknowledges the event, and a redelivery skips the subscriptions already
recorded. A trigger's firing writes the same row through ``fire()``: the
execution repository it is given stamps the stream cause on it, and the router
then sets its verdict, reason and score.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from agentarea_streams.domain import HandlerResult, StreamEvent, SubscriptionView, Verdict
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import ExecutionStatus
from .orm import TriggerExecutionORM
from .repository import TriggerExecutionRepository

_STATUS = {
    Verdict.REACTED: ExecutionStatus.SUCCESS,
    Verdict.SKIPPED: ExecutionStatus.SKIPPED,
    Verdict.ERROR: ExecutionStatus.FAILED,
}
_VERDICT = {
    ExecutionStatus.SUCCESS.value: Verdict.REACTED,
    ExecutionStatus.SKIPPED.value: Verdict.SKIPPED,
}
_UNIQUE = "uq_trigger_executions_subscription_event"


def verdict_of_status(status: str) -> Verdict:
    return _VERDICT.get(status, Verdict.ERROR)


@dataclass(frozen=True)
class StreamCause:
    """The subscription and bus event a reaction answers."""

    subscription_id: UUID
    trigger_id: UUID | None
    stream_id: UUID
    event_id: UUID
    correlation_id: str
    causation_id: str

    @classmethod
    def of(cls, subscription: SubscriptionView, event: StreamEvent) -> "StreamCause":
        return cls(
            subscription_id=subscription.id,
            trigger_id=subscription.trigger_id,
            stream_id=event.stream_id,
            event_id=event.id,
            correlation_id=event.correlation_id or str(event.id),
            causation_id=str(event.id),
        )

    def columns(self) -> dict[str, Any]:
        return {
            "subscription_id": self.subscription_id,
            "stream_id": self.stream_id,
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
        }


class ReactionRepository(WorkspaceScopedRepository[TriggerExecutionORM]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, TriggerExecutionORM, user_context)

    async def recorded_subscriptions(self, event_id: UUID) -> set[UUID]:
        result = await self.session.execute(
            select(TriggerExecutionORM.subscription_id).where(
                TriggerExecutionORM.event_id == event_id,
                TriggerExecutionORM.subscription_id.is_not(None),
                self._get_workspace_filter(),
            )
        )
        return {s for s in result.scalars().all() if s is not None}

    def _row(self, cause: StreamCause, values: dict[str, Any], now: datetime) -> dict[str, Any]:
        return {
            "id": uuid4(),
            "trigger_id": cause.trigger_id,
            "executed_at": now,
            "execution_time_ms": 0,
            "trigger_data": {},
            "derived_event_ids": [],
            **values,
            **cause.columns(),
            "workspace_id": self.user_context.workspace_id,
            "created_by": self.user_context.user_id,
            "created_at": now,
            "updated_at": now,
        }

    async def insert_once(
        self, cause: StreamCause, values: dict[str, Any], *, now: datetime
    ) -> tuple[TriggerExecutionORM, bool]:
        """Insert unless the (subscription, event) already has a row.

        Returns the row there and whether this call wrote it.
        """
        row = self._row(cause, values, now)
        if "verdict" not in values:
            row["verdict"] = verdict_of_status(str(row["status"])).value
            row["reason"] = row.get("error_message")
        inserted = await self.session.execute(
            pg_insert(TriggerExecutionORM)
            .values(**row)
            .on_conflict_do_nothing(constraint=_UNIQUE)
            .returning(TriggerExecutionORM.id)
        )
        wrote = inserted.scalar_one_or_none() is not None
        stored = await self.of_event(cause.subscription_id, cause.event_id)
        if stored is None:
            raise RuntimeError(
                f"reaction of {cause.subscription_id} to {cause.event_id} vanished after insert"
            )
        return stored, wrote

    async def record(self, cause: StreamCause, result: HandlerResult, *, now: datetime) -> None:
        """Insert the reaction, or give the row a firing wrote its verdict, reason and score."""
        values = {
            "status": _STATUS[result.verdict].value,
            "verdict": result.verdict.value,
            "reason": result.reason,
            "error_message": result.reason if result.verdict is Verdict.ERROR else None,
            "score": result.score,
            "task_id": result.task_id,
            "derived_event_ids": [str(e) for e in result.derived_event_ids],
        }
        statement = pg_insert(TriggerExecutionORM).values(**self._row(cause, values, now))
        excluded = statement.excluded
        await self.session.execute(
            statement.on_conflict_do_update(
                constraint=_UNIQUE,
                set_={
                    "verdict": excluded.verdict,
                    "reason": func.coalesce(excluded.reason, TriggerExecutionORM.reason),
                    "score": func.coalesce(excluded.score, TriggerExecutionORM.score),
                    "task_id": func.coalesce(TriggerExecutionORM.task_id, excluded.task_id),
                    "derived_event_ids": excluded.derived_event_ids,
                    "updated_at": now,
                },
            )
        )

    async def of_event(self, subscription_id: UUID, event_id: UUID) -> TriggerExecutionORM | None:
        result = await self.session.execute(
            select(TriggerExecutionORM).where(
                TriggerExecutionORM.subscription_id == subscription_id,
                TriggerExecutionORM.event_id == event_id,
                self._get_workspace_filter(),
            )
        )
        return result.scalar_one_or_none()

    async def reacted_task(self, subscription_id: UUID, event_id: UUID) -> UUID | None:
        row = await self.of_event(subscription_id, event_id)
        if row is None or row.verdict != Verdict.REACTED.value:
            return None
        return row.task_id

    async def delete_for_event(self, subscription_id: UUID, event_id: UUID) -> None:
        await self.session.execute(
            delete(TriggerExecutionORM).where(
                TriggerExecutionORM.subscription_id == subscription_id,
                TriggerExecutionORM.event_id == event_id,
                self._get_workspace_filter(),
            )
        )

    async def list_for_events(
        self, stream_id: UUID, event_ids: list[UUID]
    ) -> list[TriggerExecutionORM]:
        if not event_ids:
            return []
        result = await self.session.execute(
            select(TriggerExecutionORM).where(
                TriggerExecutionORM.stream_id == stream_id,
                TriggerExecutionORM.event_id.in_(event_ids),
                TriggerExecutionORM.subscription_id.is_not(None),
                self._get_workspace_filter(),
            )
        )
        return list(result.scalars().all())

    async def list_for_subscription(
        self, subscription_id: UUID, limit: int
    ) -> list[TriggerExecutionORM]:
        result = await self.session.execute(
            select(TriggerExecutionORM)
            .where(
                TriggerExecutionORM.subscription_id == subscription_id,
                self._get_workspace_filter(),
            )
            .order_by(TriggerExecutionORM.executed_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class CausedExecutionRepository(TriggerExecutionRepository):
    """The execution repository a stream-fired trigger records through.

    Every row it creates is that subscription's reaction to that event, written
    once: a follow-up claim may have written it first.
    """

    def __init__(self, session: AsyncSession, user_context: UserContext, cause: StreamCause):
        super().__init__(session, user_context)
        self._cause = cause

    async def create(self, **kwargs: Any) -> TriggerExecutionORM:
        reactions = ReactionRepository(self.session, self.user_context)
        try:
            row, _ = await reactions.insert_once(
                self._cause,
                {k: v for k, v in kwargs.items() if k not in ("id", "workspace_id", "created_by")},
                now=kwargs.get("executed_at") or datetime.utcnow(),
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return row


class TriggerExecutionReactionLog:
    """The streams ``ReactionLog`` port over trigger_executions."""

    def __init__(self, clock=datetime.utcnow):
        self._clock = clock

    @staticmethod
    def _reactions(session: AsyncSession, workspace_id: str, user_id: str) -> ReactionRepository:
        return ReactionRepository(session, UserContext(user_id=user_id, workspace_id=workspace_id))

    async def recorded(self, session: AsyncSession, event: StreamEvent) -> set[UUID]:
        return await self._reactions(
            session, event.workspace_id, event.created_by
        ).recorded_subscriptions(event.id)

    async def record(
        self,
        session: AsyncSession,
        subscription: SubscriptionView,
        event: StreamEvent,
        result: HandlerResult,
    ) -> None:
        await self._reactions(session, subscription.workspace_id, subscription.created_by).record(
            StreamCause.of(subscription, event), result, now=self._clock()
        )
