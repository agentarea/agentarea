"""Copy an event into other streams: no model, a causation link, an idempotent key.

A forward never writes into its own input (``StreamService.create_forward``
refuses it), so only the causation depth is checked here; it bounds a chain of
forwards that loops back through other streams.

Outputs are appended in stream id order. Each ``append`` locks its target
``streams`` row until the dispatcher commits, so two forwards that share
outputs would otherwise lock them in opposite orders and deadlock.

Over the workspace write quota, ``append`` raises ``StreamQuotaExceededError``
and so does this handler: the dispatcher counts it as a failed attempt and
retries with backoff, and only after ``MAX_ATTEMPTS`` records an ``error``
outcome. The event is never dropped silently.
"""

from agentarea_common.auth.context import UserContext
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.events.ports import IntegrationEvent
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import Verdict
from ..domain.keys import forward_event_key
from ..domain.models import HandlerResult, JournaledEvent, SubscriptionView
from ..infrastructure.journal_repository import StreamJournal


class ForwardHandler:
    def __init__(self, settings: EventStreamSettings):
        self._settings = settings

    async def handle(
        self, subscription: SubscriptionView, event: JournaledEvent, session: AsyncSession
    ) -> HandlerResult:
        depth = event.depth + 1
        if depth > self._settings.FORWARD_DEPTH:
            return HandlerResult(
                verdict=Verdict.ERROR,
                reason=f"causation depth {depth} exceeds {self._settings.FORWARD_DEPTH}",
            )
        journal = StreamJournal(
            session,
            UserContext(user_id=subscription.created_by, workspace_id=subscription.workspace_id),
            self._settings,
        )
        derived: list[int] = []
        for output in sorted(subscription.output_stream_ids):
            result = await journal.append(
                output,
                IntegrationEvent(
                    type=event.type,
                    source=f"stream:{event.stream_id}",
                    subject=event.subject,
                    time=event.time,
                    correlation_id=event.correlation_id or str(event.id),
                    causation_id=str(event.id),
                    data=event.data,
                ),
                event_key=forward_event_key(event.stream_id, event.sequence),
                depth=depth,
            )
            derived.append(result.sequence)
        return HandlerResult(verdict=Verdict.REACTED, derived_sequences=derived)
