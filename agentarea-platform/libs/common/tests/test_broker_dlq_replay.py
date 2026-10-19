"""Dead-letter replay against a live Redis; skipped when AGENTAREA_REDIS_URL is unreachable."""

from __future__ import annotations

import os
import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from agentarea_common.broker import RedisStreamsBroker
from agentarea_common.broker.dlq import (
    DEAD_LETTER_REASON_FIELD,
    DEAD_LETTER_SOURCE_FIELD,
    replay_dead_letters,
)
from agentarea_common.broker.routes import ConsumerGroupRoute, configured_routes, routes_for_dlq
from agentarea_common.config.streams import EventStreamSettings

REDIS_URL = os.getenv("AGENTAREA_REDIS_URL", "redis://localhost:6379")


@pytest_asyncio.fixture()
async def broker():
    b = RedisStreamsBroker(REDIS_URL, namespace="test")
    try:
        await b.length(f"test:smoke:{uuid.uuid4()}")
    except Exception as exc:
        pytest.skip(f"Redis not reachable: {exc}")
    yield b
    await b.aclose()


@pytest.fixture
def streams() -> tuple[str, str]:
    source = f"test:replay:{uuid.uuid4()}"
    return source, f"{source}.dlq"


async def _dead_letter(broker: RedisStreamsBroker, dlq: str, n: int) -> str:
    return await broker.submit(
        dlq, {"n": str(n), DEAD_LETTER_REASON_FIELD: "boom"}, retention=timedelta(hours=1)
    )


async def test_replay_moves_every_dead_letter_back_without_the_reason(broker, streams):
    source, dlq = streams
    for n in range(3):
        await _dead_letter(broker, dlq, n)

    result = await replay_dead_letters(broker, dlq_stream=dlq, targets=[source], batch_size=2)

    assert result.moved == 3
    assert await broker.length(dlq) == 0
    replayed = await broker.read_range(source)
    assert [m.fields for m in replayed] == [{"n": "0"}, {"n": "1"}, {"n": "2"}]


async def test_replay_by_id_range_leaves_the_rest(broker, streams):
    source, dlq = streams
    ids = [await _dead_letter(broker, dlq, n) for n in range(4)]

    result = await replay_dead_letters(
        broker, dlq_stream=dlq, targets=[source], start=ids[1], end=ids[2]
    )

    assert result.moved == 2
    assert [m.id for m in await broker.read_range(dlq)] == [ids[0], ids[3]]
    assert [m.fields for m in await broker.read_range(source)] == [{"n": "1"}, {"n": "2"}]


async def test_replaying_twice_moves_nothing_the_second_time(broker, streams):
    source, dlq = streams
    await _dead_letter(broker, dlq, 0)

    first = await replay_dead_letters(broker, dlq_stream=dlq, targets=[source])
    second = await replay_dead_letters(broker, dlq_stream=dlq, targets=[source])

    assert first.moved == 1
    assert second.moved == 0
    assert await broker.length(source) == 1


async def test_a_shared_dead_letter_stream_replays_each_letter_to_its_own_partition(broker):
    base = f"test.replay.{uuid.uuid4()}"
    partitions = [f"{base}.0", f"{base}.1"]
    dlq = f"{base}.router.dlq"
    for n, source in enumerate([partitions[1], partitions[0], f"{base}.9"]):
        await broker.submit(
            dlq,
            {"n": str(n), DEAD_LETTER_REASON_FIELD: "boom", DEAD_LETTER_SOURCE_FIELD: source},
            retention=timedelta(hours=1),
        )

    result = await replay_dead_letters(broker, dlq_stream=dlq, targets=partitions)

    assert (result.moved, result.skipped) == (2, 1)
    assert [m.fields for m in await broker.read_range(partitions[0])] == [{"n": "1"}]
    assert [m.fields for m in await broker.read_range(partitions[1])] == [{"n": "0"}]
    assert [m.fields["n"] for m in await broker.read_range(dlq)] == ["2"]


def test_configured_routes_pair_each_group_with_its_dead_letter_stream():
    routes = configured_routes(EventStreamSettings(PARTITIONS=2))

    assert routes == (
        ConsumerGroupRoute(
            stream="streams.ingest", group="ingest", dlq="streams.ingest.ingest.dlq"
        ),
        ConsumerGroupRoute(
            stream="tasks.events", group="delivery", dlq="tasks.events.delivery.dlq"
        ),
        ConsumerGroupRoute(
            stream="tasks.events", group="platform", dlq="tasks.events.platform.dlq"
        ),
        ConsumerGroupRoute(
            stream="streams.events.0", group="router", dlq="streams.events.router.dlq"
        ),
        ConsumerGroupRoute(
            stream="streams.events.1", group="router", dlq="streams.events.router.dlq"
        ),
        ConsumerGroupRoute(
            stream="streams.events.0", group="events-view", dlq="streams.events.events-view.dlq"
        ),
        ConsumerGroupRoute(
            stream="streams.events.1", group="events-view", dlq="streams.events.events-view.dlq"
        ),
    )
    assert [r.stream for r in routes_for_dlq(routes, "tasks.events.delivery.dlq")] == [
        "tasks.events"
    ]
    assert [r.stream for r in routes_for_dlq(routes, "streams.events.router.dlq")] == [
        "streams.events.0",
        "streams.events.1",
    ]
    with pytest.raises(LookupError, match=r"known: streams\.events\.events-view\.dlq, "):
        routes_for_dlq(routes, "router.dlq")
