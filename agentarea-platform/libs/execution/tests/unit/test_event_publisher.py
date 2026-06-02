from __future__ import annotations

from agentarea_common.events.base_events import DomainEvent
from agentarea_common.events.broker import EventBroker
from agentarea_execution.activities.event_publisher import create_event_publisher


class CapturingEventBroker(EventBroker):
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


async def test_create_event_publisher_accepts_event_broker_instance() -> None:
    broker = CapturingEventBroker()
    publish_chunk = create_event_publisher(broker, "task-1")

    await publish_chunk("pong", 0, is_final=True)

    assert len(broker.events) == 1
    assert broker.events[0].event_type == "workflow.LLMCallChunk"
    assert broker.events[0].data["original_data"]["task_id"] == "task-1"
    assert broker.events[0].data["original_data"]["chunk"] == "pong"
