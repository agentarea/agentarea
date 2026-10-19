"""Domain events onto the broker: ``domain.events.<type>`` (ADR-0040 §5, ADR-0043 §2).

What the outbox relay publishes. The envelope keeps its id and time, so a row
the relay publishes twice is the same event to every reader.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from agentarea_common.broker.topics import domain_events_topic

from .base_events import DomainEvent, EventEnvelope
from .broker import EventBroker
from .ports import EventPublisher, IntegrationEvent

if TYPE_CHECKING:
    from .event_models import BaseEvent

_SOURCE = "agentarea-outbox"


class DomainEventPublisher(EventBroker):
    def __init__(self, publisher: EventPublisher) -> None:
        self._publisher = publisher

    async def publish(self, event: DomainEvent | EventEnvelope | BaseEvent) -> None:
        event_any = cast(Any, event)
        to_envelope = getattr(event_any, "to_envelope", None)
        envelope = (
            cast(EventEnvelope, to_envelope())
            if callable(to_envelope)
            else EventEnvelope.from_any(cast("EventEnvelope | DomainEvent", event))
        )
        aggregate_id = envelope.data.get("aggregate_id")
        await self._publisher.publish(
            IntegrationEvent(
                id=envelope.event_id,
                type=envelope.event_type,
                source=_SOURCE,
                time=envelope.timestamp,
                subject=str(aggregate_id) if aggregate_id else None,
                data=envelope.data,
            ),
            topic=domain_events_topic(envelope.event_type),
        )
