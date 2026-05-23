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
async def streams():
    """Per-test stream + group + dlq names so parallel runs don't collide."""
    test_id = uuid.uuid4().hex[:8]
    yield {
        "stream": f"test:delivery:{test_id}",
        "group": "delivery",
        "dlq": f"test:delivery:dlq:{test_id}",
        "test_id": test_id,
    }


@pytest_asyncio.fixture()
async def broker(streams):
    b = RedisStreamsBroker(REDIS_URL)
    try:
        await b.ensure_group(streams["stream"], streams["group"], start="0")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Redis not reachable: {exc}")
    yield b
    await b.aclose()


@pytest_asyncio.fixture()
async def dedup(streams):
    d = DedupCache(REDIS_URL, prefix=f"test-dedup-{streams['test_id']}", ttl_seconds=60)
    yield d
    await d.aclose()


async def _drain(consumer: ChannelDeliveryConsumer, ticks: int = 10) -> None:
    """Run consumer for a few iterations against an already-populated stream."""
    await consumer.start()
    for _ in range(ticks):
        await asyncio.sleep(0.05)
    await consumer.stop()


async def test_success_path_acks_and_delivers(broker, dedup, streams):
    adapter = FakeAdapter()
    emitter = ChannelDeliveryEmitter(broker, stream=streams["stream"])
    consumer = ChannelDeliveryConsumer(
        broker=broker,
        dedup=dedup,
        adapter_resolver=lambda _t: adapter,
        stream=streams["stream"],
        group=streams["group"],
        dlq_stream=streams["dlq"],
        consumer_id="c-test",
        block_ms=200,
    )

    await emitter.submit(
        channel_type="telegram",
        channel_config={"chat_id": 42},
        message="hello",
        dedup_key=f"key-{streams['test_id']}",
    )

    await _drain(consumer)

    assert len(adapter.sent) == 1
    cfg, msg = adapter.sent[0]
    assert cfg["chat_id"] == 42
    assert msg == "hello"


async def test_retryable_error_leaves_message_for_redelivery(broker, dedup, streams):
    adapter = FakeAdapter()
    adapter.fail_count_remaining = 1
    adapter.fail_kind = RetryableError

    emitter = ChannelDeliveryEmitter(broker, stream=streams["stream"])
    consumer = ChannelDeliveryConsumer(
        broker=broker,
        dedup=dedup,
        adapter_resolver=lambda _t: adapter,
        stream=streams["stream"],
        group=streams["group"],
        dlq_stream=streams["dlq"],
        consumer_id="c-test",
        block_ms=200,
    )

    await emitter.submit(
        channel_type="telegram",
        channel_config={"chat_id": 7},
        message="retry me",
        dedup_key=f"retry-{streams['test_id']}",
    )
    await _drain(consumer, ticks=5)

    # Adapter raised, send not in sent[]; message stays un-ACKed.
    assert adapter.sent == []
    assert adapter.fail_count_remaining == 0


async def test_fatal_error_dead_letters_and_acks(broker, dedup, streams):
    adapter = FakeAdapter()
    adapter.fail_count_remaining = 1
    adapter.fail_kind = FatalError

    emitter = ChannelDeliveryEmitter(broker, stream=streams["stream"])
    consumer = ChannelDeliveryConsumer(
        broker=broker,
        dedup=dedup,
        adapter_resolver=lambda _t: adapter,
        stream=streams["stream"],
        group=streams["group"],
        dlq_stream=streams["dlq"],
        consumer_id="c-test",
        block_ms=200,
    )

    await emitter.submit(
        channel_type="telegram",
        channel_config={"chat_id": 99},
        message="rip",
        dedup_key=f"fatal-{streams['test_id']}",
    )
    await _drain(consumer, ticks=5)

    assert adapter.sent == []

    # DLQ now holds the entry — check via direct XLEN on the test DLQ stream.
    import redis.asyncio as redis
    client = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        assert await client.xlen(streams["dlq"]) >= 1
    finally:
        await client.aclose()


async def test_duplicate_dedup_key_only_sends_once(broker, dedup, streams):
    adapter = FakeAdapter()
    emitter = ChannelDeliveryEmitter(broker, stream=streams["stream"])
    consumer = ChannelDeliveryConsumer(
        broker=broker,
        dedup=dedup,
        adapter_resolver=lambda _t: adapter,
        stream=streams["stream"],
        group=streams["group"],
        dlq_stream=streams["dlq"],
        consumer_id="c-test",
        block_ms=200,
    )

    key = f"dup-{streams['test_id']}"
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
    await _drain(consumer)

    assert len(adapter.sent) == 1
    assert adapter.sent[0][1] == "first"


async def test_retryable_error_releases_dedup_key(broker, dedup, streams):
    """Regression for the M5 race: on RetryableError, the consumer must
    release the dedup claim so a redelivered/autoclaimed copy can retry.
    Without release, the next attempt would dedup-hit, ACK, and silently
    drop the message — turning every transient failure into permanent loss.
    """
    key = f"retry-release-{streams['test_id']}"

    # Claim the key as if we just attempted send, then call release.
    assert await dedup.claim(key) is True
    assert await dedup.claim(key) is False  # would block a retry

    adapter = FakeAdapter()
    adapter.fail_count_remaining = 1
    adapter.fail_kind = RetryableError

    emitter = ChannelDeliveryEmitter(broker, stream=streams["stream"])
    consumer = ChannelDeliveryConsumer(
        broker=broker,
        dedup=dedup,
        adapter_resolver=lambda _t: adapter,
        stream=streams["stream"],
        group=streams["group"],
        dlq_stream=streams["dlq"],
        consumer_id="c-test",
        block_ms=200,
    )

    # First, manually release so the consumer's claim succeeds fresh.
    await dedup.release(key)

    await emitter.submit(
        channel_type="telegram",
        channel_config={"chat_id": 7},
        message="must release on retry",
        dedup_key=key,
    )
    await _drain(consumer, ticks=5)

    # After the consumer ran and hit RetryableError, the dedup key must be
    # released — a fresh claim must succeed.
    assert await dedup.claim(key) is True


async def test_unknown_channel_type_dead_letters(broker, dedup, streams):
    emitter = ChannelDeliveryEmitter(broker, stream=streams["stream"])
    consumer = ChannelDeliveryConsumer(
        broker=broker,
        dedup=dedup,
        adapter_resolver=lambda _t: None,  # always None → unknown channel
        stream=streams["stream"],
        group=streams["group"],
        dlq_stream=streams["dlq"],
        consumer_id="c-orphan",
        block_ms=200,
    )

    await emitter.submit(
        channel_type="not_a_real_channel",
        channel_config={"chat_id": 1},
        message="orphan",
        dedup_key=f"orphan-{streams['test_id']}",
    )
    await _drain(consumer)

    import redis.asyncio as redis
    client = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        assert await client.xlen(streams["dlq"]) >= 1
    finally:
        await client.aclose()
