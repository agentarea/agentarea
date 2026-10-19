"""What a batch workflow's activities do: fire the trigger once for a batch, or close it.

Firing reads the batch's events back from the events read model (the workflow
holds only their ids), starts one task told every event, and settles each
event's ``batched`` reaction with that task, so the feed shows every event as
handled by it. Each event's tally is written again and its page told. An
event already settled (it reached an earlier batch too) is left out. A trigger
switched off or deleted while the batch was open starts no task: its events
are recorded as skipped.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_execution.workflows.trigger_batch_workflow import BatchSpec, OpenBatch
from agentarea_streams.domain import HandlerResult, RecordedEvent, StreamEvent, Verdict
from agentarea_streams.domain.ports import EventNotices
from agentarea_streams.infrastructure.event_repository import StreamEventRepository
from agentarea_streams.infrastructure.orm import StreamSubscriptionORM
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .batches import batch_event, batch_task_id, batch_trigger_event
from .delivery_address import event_body, firing_delivery
from .infrastructure.batch_repository import BatchReactionRepository
from .infrastructure.reaction_feed_repository import ReactionFeedRepository
from .infrastructure.reactions import CausedExecutionRepository, StreamCause
from .trigger_service import TriggerService

logger = logging.getLogger(__name__)

_VERDICTS = {"reacted": Verdict.REACTED, "skipped": Verdict.SKIPPED, "error": Verdict.ERROR}

TriggerServiceFactory = Callable[[AsyncSession, UserContext], TriggerService]
_Decide = Callable[
    [AsyncSession, UserContext, OpenBatch, list[RecordedEvent], list[StreamCause]],
    Awaitable[HandlerResult],
]


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def retally(session: AsyncSession, context: UserContext, event: StreamEvent) -> None:
    """Write the event's reaction tally again from its recorded reactions."""
    tally = await ReactionFeedRepository(session, context).tally(event.id)
    await StreamEventRepository(session, context).mark_reactions(event, tally)


async def close_open_batches(
    session: AsyncSession, context: UserContext, trigger_id: UUID, reason: str
) -> list[str]:
    """Skip every event held in an open batch of the trigger; the batches' workflow ids.

    Runs before a trigger is switched off or deleted, in the same transaction:
    deleting it deletes its reactions, and the tally written here is what the
    feed keeps.
    """
    batches = BatchReactionRepository(session, context)
    held = await batches.held_by_trigger(trigger_id)
    if not held:
        return []
    await batches.skip_held(trigger_id, reason, now=_utcnow())
    events = StreamEventRepository(session, context)
    for event_id in dict.fromkeys(row.event_id for row in held if row.event_id is not None):
        event = await events.read_by_id(event_id)
        if event is None:
            logger.warning("Event %s held in a batch of %s is not recorded", event_id, trigger_id)
            continue
        await retally(session, context, event)
    return sorted({row.workflow_id for row in held if row.workflow_id})


class TriggerBatchFirer:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        trigger_service_factory: TriggerServiceFactory,
        notices: EventNotices,
        clock: Callable[[], datetime] = _utcnow,
    ):
        self._session_factory = session_factory
        self._trigger_service_factory = trigger_service_factory
        self._notices = notices
        self._clock = clock

    async def fire(self, batch: OpenBatch) -> int:
        """Fire the trigger once for the batch; how many events it settled."""
        return await self._settle(batch, self._fired)

    async def close(self, batch: OpenBatch) -> int:
        """Record the batch's events as skipped, with the batch's reason; no task."""

        async def skipped(*_: Any) -> HandlerResult:
            return HandlerResult(verdict=Verdict.SKIPPED, reason=batch.reason)

        return await self._settle(batch, skipped)

    async def _settle(self, batch: OpenBatch, decide: _Decide) -> int:
        spec = batch.spec
        context = UserContext(user_id=spec.configured_by, workspace_id=spec.workspace_id)
        with workspace_scope(spec.workspace_id):
            async with self._session_factory() as session:
                if not await self._subscribed(session, spec):
                    # Deleted with its trigger: its reactions went with it, and the
                    # tally was written when it was deleted (close_open_batches).
                    logger.info(
                        "Batch %s of deleted trigger %s settles nothing",
                        batch.workflow_id,
                        spec.trigger_id,
                    )
                    return 0
                reactions = BatchReactionRepository(session, context)
                events = await self._events(
                    session,
                    context,
                    await reactions.unsettled(spec.subscription_id, batch.event_ids),
                )
                if not events:
                    return 0
                causes = [self._cause(spec, event) for event in events]
                result = await decide(session, context, batch, events, causes)
                await reactions.settle(
                    causes, result, workflow_id=batch.workflow_id, now=self._clock()
                )
                for event in events:
                    await retally(session, context, event)
                await session.commit()
            for event in events:
                await self._notices.processing(event)
        logger.info(
            "Batch %s of trigger %s settled %d events: %s",
            batch.workflow_id,
            spec.trigger_id,
            len(events),
            result.verdict.value,
        )
        return len(events)

    @staticmethod
    async def _subscribed(session: AsyncSession, spec: BatchSpec) -> bool:
        row = await session.get(StreamSubscriptionORM, spec.subscription_id)
        return row is not None and row.workspace_id == spec.workspace_id

    @staticmethod
    async def _events(
        session: AsyncSession, context: UserContext, event_ids: list[UUID]
    ) -> list[RecordedEvent]:
        repository = StreamEventRepository(session, context)
        events = []
        for event_id in event_ids:
            event = await repository.read_by_id(event_id)
            if event is None:
                logger.warning("Event %s of a batch is not in the events read model", event_id)
                continue
            events.append(event)
        return events

    @staticmethod
    def _cause(spec: BatchSpec, event: StreamEvent) -> StreamCause:
        return StreamCause(
            subscription_id=spec.subscription_id,
            trigger_id=spec.trigger_id,
            stream_id=event.stream_id,
            event_id=event.id,
            correlation_id=event.correlation_id or str(event.id),
            causation_id=str(event.id),
        )

    def _service(
        self, session: AsyncSession, context: UserContext, cause: StreamCause
    ) -> TriggerService:
        service = self._trigger_service_factory(session, context)
        service.trigger_execution_repository = CausedExecutionRepository(session, context, cause)
        return service

    async def _fired(
        self,
        session: AsyncSession,
        context: UserContext,
        batch: OpenBatch,
        events: list[RecordedEvent],
        causes: list[StreamCause],
    ) -> HandlerResult:
        from agentarea_tasks.domain.models import TaskProvenance

        spec = batch.spec
        service = self._service(session, context, causes[0])
        trigger = await service.get_trigger(spec.trigger_id)
        if trigger is None:
            return HandlerResult(verdict=Verdict.SKIPPED, reason="trigger no longer exists")
        if not trigger.is_active:
            return HandlerResult(verdict=Verdict.SKIPPED, reason="trigger is inactive")
        stream = await service.stream_service.get_stream(events[0].stream_id)
        entries = [batch_event(e, await event_body(e.data, e.workspace_id)) for e in events]
        told = batch_trigger_event(entries, stream_name=stream.name)
        newest = events[-1]
        delivery = await firing_delivery(
            session,
            newest,
            trigger_id=trigger.id,
            session_setting=None,
            body=entries[-1]["data"].get("body"),
        )
        if spec.caller is not None:
            service = self._service(
                session, UserContext(user_id=spec.caller, workspace_id=spec.workspace_id), causes[0]
            )
        firing = await service.fire(
            trigger.id,
            told.data,
            event=told,
            task_id=batch_task_id(spec.subscription_id, batch.event_ids[0]),
            provenance=TaskProvenance(
                origin_type="trigger",
                origin_id=str(trigger.id),
                correlation_id=causes[-1].correlation_id,
                causation_id=causes[-1].causation_id,
                depth=max(e.depth for e in events),
            ),
            raise_retryable=True,
            caller=spec.caller,
            # A batch is not one event: no follow-up joins its task, and it names no event.
            delivery=replace(delivery, stream_event_id=None, session=None),
            evaluate_conditions=False,
        )
        reason = f"fired with {len(events)} events of batch {batch.workflow_id}"
        return HandlerResult(
            verdict=_VERDICTS[firing.outcome],
            reason=reason if firing.outcome == "reacted" else firing.reason,
            task_id=firing.task_id,
        )
