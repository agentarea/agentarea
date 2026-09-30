"""LLM chunk snapshots are cumulative, so publishing one per provider delta
sends O(n^2) bytes. The publisher coalesces deltas into at most one snapshot per
interval, and never drops the final snapshot or a switch between text and
thinking.
"""

from __future__ import annotations

from agentarea_common.events.adapters.redis_streams import decode
from agentarea_common.events.ports import IntegrationEvent
from agentarea_execution.activities.event_publisher import create_event_publisher


class CapturingStreamBroker:
    def __init__(self) -> None:
        self.events: list[IntegrationEvent] = []

    async def submit(self, topic, fields, *, maxlen=None, ttl_seconds=None) -> str:
        self.events.append(decode(fields))
        return f"{len(self.events)}-0"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _snapshots(stream: CapturingStreamBroker) -> list[tuple[str, str, bool]]:
    return [(e.data["chunk"], e.data["thinking"], e.data["is_final"]) for e in stream.events]


async def test_deltas_inside_the_interval_are_coalesced_and_the_final_snapshot_is_sent():
    stream, clock = CapturingStreamBroker(), FakeClock()
    publish = create_event_publisher(
        stream, "task-1", execution_id="e", iteration=1, min_interval_seconds=0.1, clock=clock
    )

    for index, delta in enumerate(["a", "b", "c", "d"]):
        clock.now = index * 0.01
        await publish(delta, index)
    await publish("", 4, is_final=True)

    assert _snapshots(stream) == [("a", "", False), ("abcd", "", True)]


async def test_a_delta_after_the_interval_sends_the_cumulative_snapshot():
    stream, clock = CapturingStreamBroker(), FakeClock()
    publish = create_event_publisher(stream, "task-1", min_interval_seconds=0.1, clock=clock)

    await publish("hel", 0)
    clock.now = 0.05
    await publish("lo", 1)
    clock.now = 0.1
    await publish(" world", 2)

    assert _snapshots(stream) == [("hel", "", False), ("hello world", "", False)]


async def test_a_switch_between_thinking_and_text_is_sent_immediately():
    stream, clock = CapturingStreamBroker(), FakeClock()
    publish = create_event_publisher(stream, "task-1", min_interval_seconds=0.1, clock=clock)

    await publish("Let", 0, chunk_type="thinking")
    await publish(" me", 1, chunk_type="thinking")
    await publish("Hi", 2)
    await publish("!", 3)

    assert _snapshots(stream) == [("", "Let", False), ("Hi", "Let me", False)]
    assert [e.data["chunk_type"] for e in stream.events] == ["thinking", "text"]


async def test_a_long_reply_sends_bounded_bytes():
    stream, clock = CapturingStreamBroker(), FakeClock()
    publish = create_event_publisher(stream, "task-1", min_interval_seconds=0.1, clock=clock)

    deltas = 4000
    for index in range(deltas):
        clock.now = index * 0.001
        await publish("abcd", index)
    await publish("", deltas, is_final=True)

    assert len(stream.events) <= deltas * 0.001 / 0.1 + 2
    assert stream.events[-1].data["chunk"] == "abcd" * deltas


async def test_a_failed_snapshot_is_dropped_without_failing_the_model_call():
    class _DownBroker:
        async def submit(self, topic, fields, *, maxlen=None, ttl_seconds=None) -> str:
            raise ConnectionError("redis down")

    publish = create_event_publisher(_DownBroker(), "task-1")

    await publish("pong", 0, is_final=True)
