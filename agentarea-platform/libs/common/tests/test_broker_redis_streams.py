"""Integration tests for RedisStreamsBroker against a live Redis (from
docker-compose). Skipped if AGENTAREA_REDIS_URL is unavailable.

Each test uses a unique stream name so parallel runs don't collide.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from agentarea_common.broker import (
    BrokerMessage,
    DedupCache,
    RedisStreamsBroker,
)

pytestmark = pytest.mark.asyncio

REDIS_URL = os.getenv("AGENTAREA_REDIS_URL", "redis://localhost:6379")
GROUP = "test-group"


@pytest_asyncio.fixture()
async def broker():
    b = RedisStreamsBroker(REDIS_URL, namespace="test")
    try:
        # Smoke: any broker call shows Redis is reachable.
        stream = f"test:smoke:{uuid.uuid4()}"
        await b.submit(stream, {"smoke": "1"}, retention=timedelta(hours=1))
    except Exception as exc:
        pytest.skip(f"Redis not reachable: {exc}")
    yield b
    await b.aclose()


@pytest.fixture
def stream_name() -> str:
    return f"test:stream:{uuid.uuid4()}"


async def test_submit_then_consume(broker: RedisStreamsBroker, stream_name: str):
    await broker.ensure_group(stream_name, GROUP, start="0")
    msg_id = await broker.submit(stream_name, {"k": "v", "n": "1"}, retention=timedelta(hours=1))

    msgs = await broker.consume(stream_name, GROUP, "c1", count=10, block_ms=500)
    assert len(msgs) == 1
    assert isinstance(msgs[0], BrokerMessage)
    assert msgs[0].id == msg_id
    assert msgs[0].fields == {"k": "v", "n": "1"}


async def test_ack_removes_from_pel(broker: RedisStreamsBroker, stream_name: str):
    await broker.ensure_group(stream_name, GROUP, start="0")
    msg_id = await broker.submit(stream_name, {"x": "y"}, retention=timedelta(hours=1))

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
    msg_id = await broker.submit(stream_name, {"a": "b"}, retention=timedelta(hours=1))

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


async def test_submit_trims_entries_older_than_the_retention(
    broker: RedisStreamsBroker, stream_name: str
):
    client = await broker._get_client()
    old = int((time.time() - 7200) * 1000)
    for n in range(500):
        await client.xadd(f"test.{stream_name}", {"n": str(n)}, id=f"{old + n}-0")
    for n in range(200):
        await broker.submit(stream_name, {"n": f"new-{n}"}, retention=timedelta(hours=1))

    entries = await broker.read_range(stream_name, count=1000)
    expired = [e for e in entries if not e.fields["n"].startswith("new-")]
    # Approximate trimming drops whole nodes: at most the one node shared with
    # the first new entries keeps expired ones.
    assert len(expired) < 100
    assert len(entries) - len(expired) == 200


async def test_each_claimed_message_carries_its_own_delivery_count(
    broker: RedisStreamsBroker, stream_name: str
):
    await broker.ensure_group(stream_name, GROUP, start="0")
    ids = [
        await broker.submit(stream_name, {"n": str(n)}, retention=timedelta(hours=1))
        for n in range(5)
    ]
    await broker.consume(stream_name, GROUP, "c1", count=5, block_ms=100)
    client = await broker._get_client()
    for _ in range(25):
        await client.xclaim(f"test.{stream_name}", GROUP, "c1", 0, [ids[0], ids[4]], idle=60_000)

    reclaimed = await broker.autoclaim(stream_name, GROUP, "c2", min_idle_ms=30_000, count=5)
    by_id = {m.id: m.delivery_count for m in reclaimed}

    # Pending entries 1-3 lie between the two claimed ones; the count of entry 4
    # must still be its own.
    assert set(by_id) == {ids[0], ids[4]}
    assert by_id[ids[0]] == by_id[ids[4]] == 27


async def test_idle_consumers_holding_nothing_are_pruned(
    broker: RedisStreamsBroker, stream_name: str
):
    await broker.ensure_group(stream_name, GROUP, start="0")
    await broker.submit(stream_name, {"n": "1"}, retention=timedelta(hours=1))
    await broker.consume(stream_name, GROUP, "busy", count=1, block_ms=100)
    await broker.consume(stream_name, GROUP, "idle", count=1, block_ms=100)

    removed = await broker.prune_consumers(stream_name, GROUP, idle_ms=-1)

    client = await broker._get_client()
    names = {c["name"] for c in await client.xinfo_consumers(f"test.{stream_name}", GROUP)}
    assert removed == 1
    assert names == {"busy"}


async def test_last_id_is_the_newest_entry(broker: RedisStreamsBroker, stream_name: str):
    assert await broker.last_id(stream_name) == "0-0"
    await broker.submit(stream_name, {"n": "1"}, retention=timedelta(hours=1))
    newest = await broker.submit(stream_name, {"n": "2"}, retention=timedelta(hours=1))
    assert await broker.last_id(stream_name) == newest


async def test_live_channels_receive_what_is_notified_while_subscribed(
    broker: RedisStreamsBroker, stream_name: str
):
    live = await broker.open_live()
    try:
        await live.subscribe(stream_name)
        await asyncio.sleep(0.1)
        await broker.notify(stream_name, {"n": "1"})
        received = None
        for _ in range(20):
            received = await live.next_message(0.2)
            if received is not None:
                break
        assert received == (stream_name, {"n": "1"})
    finally:
        await live.aclose()


async def test_ensure_group_idempotent(broker: RedisStreamsBroker, stream_name: str):
    await broker.ensure_group(stream_name, GROUP)
    # Second call must not raise BUSYGROUP.
    await broker.ensure_group(stream_name, GROUP)


async def test_dedup_first_claim_succeeds_duplicate_fails():
    cache = DedupCache(REDIS_URL, namespace="test", prefix="test-dedup", ttl_seconds=60)
    try:
        key = f"k:{uuid.uuid4()}"
        try:
            first = await cache.claim(key)
        except Exception as exc:
            pytest.skip(f"Redis not reachable: {exc}")
        assert first is True
        assert await cache.claim(key) is False
        client = await cache._get_client()
        assert await client.exists(f"test.dedup.test-dedup:{key}") == 1
    finally:
        await cache.aclose()


async def test_group_info_reports_undelivered_entries_as_lag(
    broker: RedisStreamsBroker, stream_name: str
):
    await broker.ensure_group(stream_name, GROUP, start="0")
    for n in range(3):
        await broker.submit(stream_name, {"n": str(n)}, retention=timedelta(hours=1))
    await broker.consume(stream_name, GROUP, "c1", count=1, block_ms=100)

    info = await broker.group_info(stream_name, GROUP)

    assert info is not None
    assert info.lag == 2
    assert info.consumers == 1


async def test_group_info_derives_lag_when_the_broker_cannot_report_it(
    broker: RedisStreamsBroker, stream_name: str
):
    await broker.ensure_group(stream_name, GROUP, start="0")
    ids = [await broker.submit(stream_name, {"n": str(n)}, retention=timedelta(hours=1)) for n in range(3)]
    client = await broker._get_client()
    await client.xdel(f"test.{stream_name}", ids[1])

    info = await broker.group_info(stream_name, GROUP)

    assert info is not None
    assert info.lag == 2


async def test_group_info_is_none_for_a_missing_stream_or_group(
    broker: RedisStreamsBroker, stream_name: str
):
    assert await broker.group_info(stream_name, GROUP) is None
    await broker.submit(stream_name, {"n": "1"}, retention=timedelta(hours=1))
    assert await broker.group_info(stream_name, GROUP) is None


async def test_pending_summary_reports_the_oldest_pending_age_a_reclaim_does_not_reset(
    broker: RedisStreamsBroker, stream_name: str
):
    await broker.ensure_group(stream_name, GROUP, start="0")
    first = await broker.submit(stream_name, {"n": "1"}, retention=timedelta(hours=1))
    await broker.consume(stream_name, GROUP, "c1", count=1, block_ms=100)
    await asyncio.sleep(0.2)
    await broker.submit(stream_name, {"n": "2"}, retention=timedelta(hours=1))
    await broker.consume(stream_name, GROUP, "c1", count=1, block_ms=100)
    await broker.autoclaim(stream_name, GROUP, "c2", min_idle_ms=0)

    summary = await broker.pending_summary(stream_name, GROUP)

    assert summary.count == 2
    assert summary.oldest_age_ms is not None
    assert summary.oldest_age_ms >= 200

    await broker.ack(stream_name, GROUP, first)
    after = await broker.pending_summary(stream_name, GROUP)
    assert after.count == 1
    assert after.oldest_age_ms is not None
    assert after.oldest_age_ms < 200


async def test_pending_summary_of_an_idle_group_is_empty(
    broker: RedisStreamsBroker, stream_name: str
):
    await broker.ensure_group(stream_name, GROUP, start="0")

    summary = await broker.pending_summary(stream_name, GROUP)

    assert summary.count == 0
    assert summary.oldest_age_ms is None


async def test_length_counts_entries_and_is_zero_for_a_missing_stream(
    broker: RedisStreamsBroker, stream_name: str
):
    assert await broker.length(stream_name) == 0
    await broker.submit(stream_name, {"n": "1"}, retention=timedelta(hours=1))
    await broker.submit(stream_name, {"n": "2"}, retention=timedelta(hours=1))
    assert await broker.length(stream_name) == 2


async def test_read_range_returns_entries_between_ids(
    broker: RedisStreamsBroker, stream_name: str
):
    ids = [await broker.submit(stream_name, {"n": str(n)}, retention=timedelta(hours=1)) for n in range(4)]

    window = await broker.read_range(stream_name, start=ids[1], end=ids[2])
    capped = await broker.read_range(stream_name, count=3)

    assert [m.id for m in window] == ids[1:3]
    assert window[0].fields == {"n": "1"}
    assert [m.id for m in capped] == ids[:3]


async def test_move_appends_to_target_and_removes_from_source_once(
    broker: RedisStreamsBroker, stream_name: str
):
    target = f"{stream_name}:target"
    msg_id = await broker.submit(stream_name, {"n": "1", "fatal_reason": "boom"}, retention=timedelta(hours=1))

    moved = await broker.move(stream_name, msg_id, target, {"n": "1"})
    again = await broker.move(stream_name, msg_id, target, {"n": "1"})

    assert moved is not None
    assert again is None
    assert await broker.length(stream_name) == 0
    landed = await broker.read_range(target)
    assert [(m.id, m.fields) for m in landed] == [(moved, {"n": "1"})]
