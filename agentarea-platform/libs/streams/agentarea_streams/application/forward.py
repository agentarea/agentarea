"""Copy an event into other streams: no model, a causation link, a derived id.

A forward never writes into its own input (``StreamService.create_forward``
refuses it), so only the causation depth is checked here; it bounds a chain of
forwards that loops back through other streams.

Each copy's id derives from ``uuid5(forward, source event id)`` and its output
stream: a redelivered event publishes the same ids again, and the bus drops the
repeats.

Over the workspace write quota, the append raises ``StreamQuotaExceededError``
and so does this handler: the event is redelivered, and past ``MAX_ATTEMPTS``
the router records an ``error`` reaction. The event is never dropped silently.
"""

from agentarea_common.auth.context import UserContext
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.events.ports import IntegrationEvent
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import Verdict
from ..domain.keys import derived_event_id
from ..domain.models import HandlerResult, StreamEvent, SubscriptionView
from ..infrastructure.bus import StreamBus
from .ingest import StreamIngest


class ForwardHandler:
    def __init__(self, settings: EventStreamSettings, bus: StreamBus):
        self._settings = settings
        self._bus = bus

    async def handle(
        self, subscription: SubscriptionView, event: StreamEvent, session: AsyncSession
    ) -> HandlerResult:
        depth = event.depth + 1
        if depth > self._settings.FORWARD_DEPTH:
            return HandlerResult(
                verdict=Verdict.ERROR,
                reason=f"causation depth {depth} exceeds {self._settings.FORWARD_DEPTH}",
            )
        ingest = StreamIngest(
            session,
            UserContext(user_id=subscription.created_by, workspace_id=subscription.workspace_id),
            self._settings,
            self._bus,
        )
        copy_id = derived_event_id(subscription.id, event.id)
        derived = [
            (output, derived_event_id(copy_id, output))
            for output in sorted(subscription.output_stream_ids)
        ]
        for output, derived_id in derived:
            await ingest.append(
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
                event_key=f"{event.stream_id}:{event.id}",
                depth=depth,
                event_id=derived_id,
            )
        return HandlerResult(
            verdict=Verdict.REACTED, derived_event_ids=[derived_id for _, derived_id in derived]
        )
