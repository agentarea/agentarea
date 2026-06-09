"""Integration tests for RedisStreamsBroker against a live Redis (from
docker-compose). Skipped if REDIS_URL is unavailable.

Each test uses a unique stream name so parallel runs don't collide.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import pytest_asyncio

from agentarea_common.broker import (
    BrokerMessage,
    DedupCache,
    RedisStreamsBroker,
)

pytestmark = pytest.mark.asyncio

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
GROUP = "test-group"


@pytest_asyncio.fixture()
async def broker():
    b = RedisStreamsBroker(REDIS_URL)
    try:
        # Smoke: any broker call shows Redis is reachable.
        stream = f"test:smoke:{uuid.uuid4()}"
        await b.submit(stream, {"smoke": "1"})
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Redis not reachable: {exc}")
    yield b
    await b.aclose()


@pytest.fixture()
def stream_name() -> str:
    return f"test:stream:{uuid.uuid4()}"


async def test_submit_then_consume(broker: RedisStreamsBroker, stream_name: str):
    await broker.ensure_group(stream_name, GROUP, start="0")
    msg_id = await broker.submit(stream_name, {"k": "v", "n": "1"})

    msgs = await broker.consume(stream_name, GROUP, "c1", count=10, block_ms=500)
    assert len(msgs) == 1
    assert isinstance(msgs[0], BrokerMessage)
    assert msgs[0].id == msg_id
    assert msgs[0].fields == {"k": "v", "n": "1"}


async def test_ack_removes_from_pel(broker: RedisStreamsBroker, stream_name: str):
    await broker.ensure_group(stream_name, GROUP, start="0")
    msg_id = await broker.submit(stream_name, {"x": "y"})

    msgs = await broker.consume(stream_name, GROUP, "c1", block_ms=500)
    assert len(msgs) == 1

    await broker.ack(stream_name, GROUP, msg_id)

    # Reconsuming with > should yield nothing (PEL is empty, no new entries).
    again = await broker.consume(stream_name, GROUP, "c1", block_ms=200)
    assert again == []


async def test_autoclaim_recovers_from_dead_consumer(
    broker: RedisStreamsBroker, stream_name: str
):
    await broker.ensure_group(stream_name, GROUP, start="0")
    msg_id = await broker.submit(stream_name, {"a": "b"})

    # c1 claims but never ACKs (simulates crash).
    claimed = await broker.consume(stream_name, GROUP, "c1", block_ms=500)
    assert len(claimed) == 1

    # Without idle wait, autoclaim with min_idle=0 hands it to c2.
    await asyncio.sleep(0.05)
    reclaimed = await broker.autoclaim(
        stream_name, GROUP, "c2", min_idle_ms=10
    )
    assert len(reclaimed) == 1
    assert reclaimed[0].id == msg_id


async def test_ensure_group_idempotent(broker: RedisStreamsBroker, stream_name: str):
    await broker.ensure_group(stream_name, GROUP)
    # Second call must not raise BUSYGROUP.
    await broker.ensure_group(stream_name, GROUP)


async def test_dedup_first_claim_succeeds_duplicate_fails():
    cache = DedupCache(REDIS_URL, prefix="test-dedup", ttl_seconds=60)
    try:
        key = f"k:{uuid.uuid4()}"
        try:
            first = await cache.claim(key)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Redis not reachable: {exc}")
        assert first is True
        assert await cache.claim(key) is False
    finally:
        await cache.aclose()
