"""Consumer-group health read on collection; Redis cases skip when AGENTAREA_REDIS_URL is unreachable."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from agentarea_common.broker import RedisStreamsBroker
from agentarea_common.broker.routes import ConsumerGroupRoute
from agentarea_common.config.broker import KafkaSettings, RedisSettings
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.observability import broker_metrics
from agentarea_common.observability.broker_metrics import (
    BrokerHealthReader,
    broker_observations,
    read_broker_health,
    start_broker_health_metrics,
)

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


def _route() -> ConsumerGroupRoute:
    stream = f"test:health:{uuid.uuid4()}"
    return ConsumerGroupRoute(stream=stream, group="g", dlq=f"{stream}.dlq")


def _values(observations: dict, name: str) -> list[tuple[float, dict]]:
    return [(o.value, dict(o.attributes or {})) for o in observations.get(name, [])]


async def test_a_read_reports_lag_pending_oldest_idle_and_dead_letters(broker):
    route = _route()
    await broker.ensure_group(route.stream, route.group, start="0")
    for n in range(3):
        await broker.submit(route.stream, {"n": str(n)}, retention=timedelta(hours=1))
    await broker.consume(route.stream, route.group, "c1", count=1, block_ms=100)
    await broker.submit(route.dlq, {"n": "x", "fatal_reason": "boom"}, retention=timedelta(hours=1))
    await asyncio.sleep(0.1)

    observations = broker_observations(await read_broker_health(broker, [route]))

    labels = {"stream": route.stream, "group": route.group}
    assert _values(observations, "agentarea.broker.group.lag") == [(2, labels)]
    assert _values(observations, "agentarea.broker.group.pending") == [(1, labels)]
    [(idle, _)] = _values(observations, "agentarea.broker.group.oldest_pending")
    assert idle >= 0.1
    assert _values(observations, "agentarea.broker.dlq.length") == [(1, {"stream": route.dlq})]
    assert _values(observations, "agentarea.broker.health") == [(1, {})]


async def test_a_group_not_yet_created_reports_no_group_values(broker):
    route = _route()

    observations = broker_observations(await read_broker_health(broker, [route]))

    assert _values(observations, "agentarea.broker.group.lag") == []
    assert _values(observations, "agentarea.broker.dlq.length") == [(0, {"stream": route.dlq})]
    assert _values(observations, "agentarea.broker.health") == [(1, {})]


def test_a_failed_read_reports_only_that_the_broker_is_down():
    observations = broker_observations(None)

    assert set(observations) == {"agentarea.broker.health"}
    assert _values(observations, "agentarea.broker.health") == [(0, {})]


class _DownBroker:
    async def group_info(self, stream: str, group: str):
        raise ConnectionError("broker down")

    async def length(self, stream: str) -> int:
        raise ConnectionError("broker down")


async def test_an_unreachable_broker_reports_down_instead_of_failing_the_collection(caplog):
    reader = BrokerHealthReader(
        _DownBroker(),  # type: ignore[arg-type]
        [_route()],
        asyncio.get_running_loop(),
        timeout_seconds=5,
    )

    observed = await asyncio.to_thread(reader.observations, "agentarea.broker.health")

    assert [o.value for o in observed] == [0]
    assert any(r.exc_info for r in caplog.records)


async def test_reading_on_the_event_loop_thread_is_refused():
    reader = BrokerHealthReader(
        _DownBroker(),  # type: ignore[arg-type]
        [_route()],
        asyncio.get_running_loop(),
        timeout_seconds=5,
    )

    assert [o.value for o in reader.observations("agentarea.broker.health")] == [0]


async def test_startup_activates_the_reader_and_close_retires_it():
    settings = SimpleNamespace(
        broker=RedisSettings(REDIS_URL=REDIS_URL),
        streams=EventStreamSettings(),
    )

    handle = start_broker_health_metrics(settings)  # type: ignore[arg-type]
    active = broker_metrics._active
    await handle.aclose()

    assert active is not None
    assert broker_metrics._active is None


async def test_startup_refuses_a_broker_without_consumer_groups_to_read():
    settings = SimpleNamespace(broker=KafkaSettings(), streams=EventStreamSettings())

    with pytest.raises(RuntimeError, match="AGENTAREA_BROKER=redis"):
        start_broker_health_metrics(settings)  # type: ignore[arg-type]
