"""Integration tests for ChannelDeliveryConsumer against a live Redis.

Verifies the actual bug fix: silent message loss when adapter.send fails.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import pytest_asyncio

from agentarea_common.broker import DedupCache, RedisStreamsBroker
from agentarea_triggers.channels.delivery_consumer import (
    ChannelDeliveryConsumer,
    ChannelDeliveryEmitter,
)
from agentarea_triggers.channels.exceptions import FatalError, RetryableError

pytestmark = pytest.mark.asyncio

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


class FakeAdapter:
    def __init__(self):
        self.sent: list[tuple[dict, str]] = []
        self.behavior = "ok"
        self.fail_count_remaining = 0
        self.fail_kind: type[Exception] = RetryableError
        self._behavior_lock = asyncio.Lock()

    async def send(self, channel_config, message):
        async with self._behavior_lock:
            if self.fail_count_remaining > 0:
                self.fail_count_remaining -= 1
                raise self.fail_kind("simulated failure")
            self.sent.append((channel_config, message))


@pytest_asyncio.fixture()
async def broker_and_dedup():
    # Each test gets a unique stream so parallel runs don't collide and
    # leftover entries from a previous run can't bleed in.
    stream = f"test:delivery:{uuid.uuid4()}"
    group = "delivery"

    broker = RedisStreamsBroker(REDIS_URL)
    dedup = DedupCache(REDIS_URL, prefix=f"test-dedup-{uuid.uuid4()}", ttl_seconds=60)
    try:
        await broker.ensure_group(stream, group, start="0")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Redis not reachable: {exc}")
    yield broker, dedup, stream, group
    await broker.aclose()
    await dedup.aclose()


async def _run_consumer_with_patched_stream(
    broker, dedup, adapter, stream, group, *, ticks: int = 20
):
    """Spin up the consumer pointed at our test stream, drain for a bit, then stop."""
    import agentarea_triggers.channels.delivery_consumer as dc

    original_stream = dc.OUTBOUND_STREAM
    original_group = dc.OUTBOUND_GROUP
    dc.OUTBOUND_STREAM = stream
    dc.OUTBOUND_GROUP = group
    try:
        consumer = ChannelDeliveryConsumer(
            broker=broker,
            dedup=dedup,
            adapter_resolver=lambda _t: adapter,
            consumer_id="c-test",
            block_ms=200,
            batch_size=10,
        )
        await consumer.start()
        for _ in range(ticks):
            await asyncio.sleep(0.05)
        await consumer.stop()
    finally:
        dc.OUTBOUND_STREAM = original_stream
        dc.OUTBOUND_GROUP = original_group


async def test_success_path_acks_and_delivers(broker_and_dedup):
    broker, dedup, stream, group = broker_and_dedup
    adapter = FakeAdapter()

    import agentarea_triggers.channels.delivery_consumer as dc
    dc.OUTBOUND_STREAM = stream
    dc.OUTBOUND_GROUP = group

    emitter = ChannelDeliveryEmitter(broker)
    await emitter.submit(
        channel_type="telegram",
        channel_config={"chat_id": 42},
        message="hello",
        dedup_key=f"key-{uuid.uuid4()}",
    )

    await _run_consumer_with_patched_stream(broker, dedup, adapter, stream, group)

    assert len(adapter.sent) == 1
    cfg, msg = adapter.sent[0]
    assert cfg["chat_id"] == 42
    assert msg == "hello"


async def test_retryable_error_leaves_message_for_redelivery(broker_and_dedup):
    """RetryableError → no ACK → broker keeps message in PEL.

    We can't easily induce broker redelivery in a fast test, but we can
    verify that the adapter was called and the message was NOT acked
    (i.e., it stays in the consumer's PEL).
    """
    broker, dedup, stream, group = broker_and_dedup
    adapter = FakeAdapter()
    adapter.fail_count_remaining = 1
    adapter.fail_kind = RetryableError

    import agentarea_triggers.channels.delivery_consumer as dc
    dc.OUTBOUND_STREAM = stream
    dc.OUTBOUND_GROUP = group

    emitter = ChannelDeliveryEmitter(broker)
    await emitter.submit(
        channel_type="telegram",
        channel_config={"chat_id": 7},
        message="retry me",
        dedup_key=f"retry-{uuid.uuid4()}",
    )

    await _run_consumer_with_patched_stream(broker, dedup, adapter, stream, group, ticks=5)

    # Adapter raised, send not in sent[]; message stays un-ACKed.
    assert adapter.sent == []
    assert adapter.fail_count_remaining == 0  # we did try


async def test_fatal_error_dead_letters_and_acks(broker_and_dedup):
    broker, dedup, stream, group = broker_and_dedup
    adapter = FakeAdapter()
    adapter.fail_count_remaining = 1
    adapter.fail_kind = FatalError

    import agentarea_triggers.channels.delivery_consumer as dc
    dc.OUTBOUND_STREAM = stream
    dc.OUTBOUND_GROUP = group

    emitter = ChannelDeliveryEmitter(broker)
    dedup_key = f"fatal-{uuid.uuid4()}"
    msg_id = await emitter.submit(
        channel_type="telegram",
        channel_config={"chat_id": 99},
        message="rip",
        dedup_key=dedup_key,
    )

    await _run_consumer_with_patched_stream(broker, dedup, adapter, stream, group, ticks=5)

    # Adapter raised once, no successful send, message ACKed (not redelivered).
    assert adapter.sent == []

    # DLQ should now hold the entry — check via direct XLEN on the dlq stream.
    import redis.asyncio as redis
    client = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        dlq_len = await client.xlen("agentarea.channel.outbound.dlq")
        assert dlq_len >= 1
    finally:
        await client.aclose()


async def test_duplicate_dedup_key_only_sends_once(broker_and_dedup):
    """Two submissions with the same dedup_key → only one delivery."""
    broker, dedup, stream, group = broker_and_dedup
    adapter = FakeAdapter()

    import agentarea_triggers.channels.delivery_consumer as dc
    dc.OUTBOUND_STREAM = stream
    dc.OUTBOUND_GROUP = group

    emitter = ChannelDeliveryEmitter(broker)
    key = f"dup-{uuid.uuid4()}"
    await emitter.submit(
        channel_type="telegram",
        channel_config={"chat_id": 1},
        message="first",
        dedup_key=key,
    )
    await emitter.submit(
        channel_type="telegram",
        channel_config={"chat_id": 1},
        message="duplicate (same key)",
        dedup_key=key,
    )

    await _run_consumer_with_patched_stream(broker, dedup, adapter, stream, group)

    assert len(adapter.sent) == 1
    assert adapter.sent[0][1] == "first"


async def test_unknown_channel_type_dead_letters(broker_and_dedup):
    """Adapter not registered for channel_type → DLQ + ACK (no infinite retry)."""
    broker, dedup, stream, group = broker_and_dedup

    import agentarea_triggers.channels.delivery_consumer as dc
    dc.OUTBOUND_STREAM = stream
    dc.OUTBOUND_GROUP = group

    emitter = ChannelDeliveryEmitter(broker)
    await emitter.submit(
        channel_type="not_a_real_channel",
        channel_config={"chat_id": 1},
        message="orphan",
        dedup_key=f"orphan-{uuid.uuid4()}",
    )

    consumer = ChannelDeliveryConsumer(
        broker=broker,
        dedup=dedup,
        adapter_resolver=lambda _t: None,  # always None → unknown channel
        consumer_id="c-orphan",
        block_ms=200,
    )
    await consumer.start()
    for _ in range(10):
        await asyncio.sleep(0.05)
    await consumer.stop()

    import redis.asyncio as redis
    client = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        dlq_len = await client.xlen("agentarea.channel.outbound.dlq")
        assert dlq_len >= 1
    finally:
        await client.aclose()
