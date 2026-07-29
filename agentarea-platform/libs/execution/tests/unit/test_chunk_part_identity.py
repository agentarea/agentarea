"""A streamed chunk must land on the same part as the completed call.

The reducer supersedes by part_id, and an llm part's id is
``f"{execution_id}:{iteration}"``. llm.call.completed carries both fields, so a
chunk that omits them derives a null part_id and never renders as streaming
text — it falls through to the raw timeline instead. These tests pin the chunk
payload against the identity the contract actually derives, rather than against
a hand-written payload the producer never emits.
"""

from agentarea_common.events.base_events import DomainEvent
from agentarea_common.events.broker import EventBroker
from agentarea_common.events.contract import derive_part
from agentarea_execution.activities.event_publisher import create_event_publisher


class CapturingBroker(EventBroker):
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


def _published_chunk_data(broker) -> dict:
    return broker.events[0].data["original_data"]


async def test_chunk_carries_the_fields_the_part_id_is_built_from() -> None:
    broker = CapturingBroker()
    publish_chunk = create_event_publisher(
        broker, "task-1", execution_id="task-1-exec", iteration=2
    )

    await publish_chunk("pong", 0)

    data = _published_chunk_data(broker)
    assert data["execution_id"] == "task-1-exec"
    assert data["iteration"] == 2


async def test_chunk_derives_a_part_instead_of_falling_through() -> None:
    broker = CapturingBroker()
    publish_chunk = create_event_publisher(
        broker, "task-1", execution_id="task-1-exec", iteration=2
    )

    await publish_chunk("pong", 0)

    part = derive_part("llm.call.chunk", _published_chunk_data(broker))
    assert part is not None, "chunk must resolve to a part, not the raw timeline"
    assert part.kind == "llm"
    assert part.part_id == "task-1-exec:2"


async def test_chunk_and_completed_call_share_one_part_id() -> None:
    # This is the whole point: the streamed text and the final message must be
    # the same part, so the final supersedes the stream in place.
    broker = CapturingBroker()
    publish_chunk = create_event_publisher(
        broker, "task-1", execution_id="task-1-exec", iteration=2
    )
    await publish_chunk("pon", 0)

    chunk_part = derive_part("llm.call.chunk", _published_chunk_data(broker))
    completed_part = derive_part(
        "llm.call.completed",
        {"task_id": "task-1", "execution_id": "task-1-exec", "iteration": 2, "content": "pong"},
    )

    assert chunk_part is not None
    assert completed_part is not None
    assert chunk_part.part_id == completed_part.part_id


async def test_chunks_of_different_iterations_are_different_parts() -> None:
    broker = CapturingBroker()
    first = create_event_publisher(broker, "task-1", execution_id="e", iteration=1)
    await first("a", 0)
    second = create_event_publisher(broker, "task-1", execution_id="e", iteration=2)
    await second("b", 0)

    parts = [derive_part("llm.call.chunk", e.data["original_data"]) for e in broker.events]
    assert parts[0] is not None
    assert parts[1] is not None
    assert parts[0].part_id != parts[1].part_id
