"""One consumer group over many topics, extension attributes, dead letters (ADR-0043 §3).

The router reads every partition of ``streams.events`` in one group. A message
that keeps failing is handed to the dead-letter callback, copied to the
dead-letter topic with the partition it came from, and acknowledged. Every
Redis key carries the namespace. Needs a live Redis (AGENTAREA_REDIS_URL);
skipped otherwise.
"""

import asyncio
import os
from uuid import uuid4

import pytest
from agentarea_common.broker import RedisStreamsBroker
from agentarea_common.broker.dlq import DEAD_LETTER_SOURCE_FIELD
from agentarea_common.broker.topics import (
    domain_events_topic,
    stream_events_partition,
    stream_events_partitions,
)
from agentarea_common.events.adapters.redis_streams import (
    RedisStreamsEventBus,
    decode,
    encode,
)
from agentarea_common.events.ports import IntegrationEvent

REDIS_URL = os.getenv("AGENTAREA_REDIS_URL", "redis://localhost:6379")


def test_extension_attributes_survive_the_wire():
    event = IntegrationEvent(
        type="push", source="webhook:github", extensions={"streamid": "s-1", "depth": "2"}
    )
    decoded = decode(encode(event))
    assert decoded.extensions == {"streamid": "s-1", "depth": "2"}
    assert decoded.id == event.id


def test_an_extension_may_not_shadow_an_envelope_attribute():
    with pytest.raises(ValueError, match="extension"):
        encode(IntegrationEvent(type="t", source="s", extensions={"type": "x"}))
    with pytest.raises(ValueError, match="extension"):
        encode(IntegrationEvent(type="t", source="s", extensions={"Stream_Id": "x"}))


def test_a_stream_always_maps_to_one_partition_of_the_fixed_set():
    stream_id = uuid4()
    partitions = stream_events_partitions(16)
    assert len(partitions) == 16
    assert partitions[0] == "streams.events.0"
    assert stream_events_partition(stream_id, 16) in partitions
    assert stream_events_partition(stream_id, 16) == stream_events_partition(stream_id, 16)
    spread = {stream_events_partition(uuid4(), 16) for _ in range(200)}
    assert len(spread) > 8


NAMESPACE = f"test{uuid4().hex[:8]}"


@pytest.fixture
async def broker():
    b = RedisStreamsBroker(REDIS_URL, namespace=NAMESPACE)
    try:
        await b.submit(f"test.smoke.{uuid4()}", {"smoke": "1"})
    except Exception as exc:
        pytest.skip(f"Redis not reachable: {exc}")
    yield b
    await b.aclose()


async def _until(predicate, timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.05)


async def test_publish_goes_to_the_named_topic_under_the_namespace(broker):
    bus = RedisStreamsEventBus(broker)
    topic = f"streams.events.{uuid4().hex[:8]}"
    event = IntegrationEvent(type="push", source="test")
    await bus.publish(event, topic=topic)
    _, messages = await broker.tail(topic, last_id="0", block_ms=100)
    assert [decode(m.fields).id for m in messages] == [event.id]
    client = await broker._get_client()
    assert await client.xlen(f"{NAMESPACE}.{topic}") == 1


async def test_publish_without_a_topic_goes_to_the_domain_events_of_its_type(broker):
    bus = RedisStreamsEventBus(broker)
    event = IntegrationEvent(type=f"t{uuid4().hex[:8]}", source="test")
    await bus.publish(event)
    _, messages = await broker.tail(domain_events_topic(event.type), last_id="0", block_ms=100)
    assert [decode(m.fields).id for m in messages] == [event.id]


async def test_one_group_reads_every_partition_including_events_from_before_it(broker):
    prefix = f"p{uuid4().hex[:8]}"
    topics = [f"{prefix}.0", f"{prefix}.1"]
    bus = RedisStreamsEventBus(broker, block_ms=100)
    seen: list[str] = []

    async def handler(event: IntegrationEvent) -> None:
        seen.append(event.type)

    async def dead(event: IntegrationEvent) -> None:
        raise AssertionError("nothing should be dead-lettered")

    await bus.publish(IntegrationEvent(type="before", source="t"), topic=topics[0])
    subscription = await bus.subscribe_many(
        topics=topics,
        group="router",
        handler=handler,
        dead_letter_topic=f"{prefix}.router.dlq",
        on_dead_letter=dead,
    )
    try:
        await bus.publish(IntegrationEvent(type="after", source="t"), topic=topics[0])
        await bus.publish(IntegrationEvent(type="other", source="t"), topic=topics[1])
        await _until(lambda: len(seen) == 3)
        assert sorted(seen) == ["after", "before", "other"]
    finally:
        await subscription.stop()


async def test_messages_name_the_logical_stream_they_came_from(broker):
    topics = [f"p{uuid4().hex[:8]}.0", f"p{uuid4().hex[:8]}.1"]
    for topic in topics:
        await broker.ensure_group(topic, "g", start="0")
        await broker.submit(topic, {"n": topic})
    fresh = await broker.consume_many(topics, "g", "c", block_ms=100)
    assert sorted(m.stream for m in fresh) == sorted(topics)
    assert all(m.fields["n"] == m.stream for m in fresh)


async def test_a_message_failing_past_the_limit_is_dead_lettered_and_acked(broker):
    prefix = f"p{uuid4().hex[:8]}"
    bus = RedisStreamsEventBus(broker, block_ms=50, min_idle_ms=10, max_delivery=2)
    attempts: list[str] = []
    dead: list[IntegrationEvent] = []

    async def handler(event: IntegrationEvent) -> None:
        attempts.append(event.type)
        raise RuntimeError("downstream unavailable")

    async def on_dead(event: IntegrationEvent) -> None:
        dead.append(event)

    event = IntegrationEvent(type="poison", source="t")
    await bus.publish(event, topic=f"{prefix}.x")
    subscription = await bus.subscribe_many(
        topics=[f"{prefix}.x", f"{prefix}.y"],
        group="router",
        handler=handler,
        dead_letter_topic=f"{prefix}.router.dlq",
        on_dead_letter=on_dead,
    )
    try:
        await _until(lambda: len(dead) == 1)
    finally:
        await subscription.stop()
    assert len(attempts) == 2
    assert dead[0].id == event.id
    _, letters = await broker.tail(f"{prefix}.router.dlq", last_id="0", block_ms=100)
    assert [decode(m.fields).id for m in letters] == [event.id]
    assert letters[0].fields[DEAD_LETTER_SOURCE_FIELD] == f"{prefix}.x"
    pending = await broker.pending_summary(f"{prefix}.x", "router")
    assert pending.count == 0
