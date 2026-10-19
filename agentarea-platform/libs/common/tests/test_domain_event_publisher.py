"""The outbox relay's domain events go to ``domain.events.<type>`` (ADR-0040 §5, ADR-0043 §2)."""

from datetime import UTC, datetime
from uuid import uuid4

from agentarea_common.broker.topics import domain_events_topic
from agentarea_common.events.base_events import DomainEvent, EventEnvelope
from agentarea_common.events.domain_events import DomainEventPublisher
from agentarea_common.events.ports import IntegrationEvent


class _Bus:
    def __init__(self) -> None:
        self.published: list[tuple[IntegrationEvent, str | None]] = []

    async def publish(self, event: IntegrationEvent, *, topic: str | None = None) -> None:
        self.published.append((event, topic))


async def test_an_outbox_envelope_is_published_to_its_domain_topic_with_its_id():
    bus = _Bus()
    event_id = uuid4()
    at = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    await DomainEventPublisher(bus).publish(
        EventEnvelope(
            event_id=event_id,
            timestamp=at,
            event_type="streams.subscriptions.changed",
            data={"stream_id": "s-1", "aggregate_id": "s-1"},
        )
    )
    ((event, topic),) = bus.published
    assert topic == domain_events_topic("streams.subscriptions.changed")
    assert (event.id, event.type, event.time) == (event_id, "streams.subscriptions.changed", at)
    assert event.subject == "s-1"
    assert event.data["stream_id"] == "s-1"


async def test_a_domain_event_is_published_as_its_envelope():
    bus = _Bus()
    await DomainEventPublisher(bus).publish(DomainEvent(event_type="TaskCreated", task_id="t-1"))
    ((event, topic),) = bus.published
    assert (event.type, topic) == ("TaskCreated", domain_events_topic("TaskCreated"))
    assert event.data["task_id"] == "t-1"
