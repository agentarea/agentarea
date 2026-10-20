"""Consumer-group health read on scrape; Redis cases skip when AGENTAREA_REDIS_URL is unreachable."""

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
from agentarea_common.observability.broker_metrics import (
    BrokerHealthCollector,
    start_broker_health_metrics,
)
from prometheus_client import CollectorRegistry

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


def _registry(broker, routes) -> CollectorRegistry:
    registry = CollectorRegistry()
    registry.register(
        BrokerHealthCollector(broker, routes, asyncio.get_running_loop(), timeout_seconds=5)
    )
    return registry


async def _sample(registry: CollectorRegistry, name: str, **labels: str) -> float | None:
    return await asyncio.to_thread(registry.get_sample_value, name, labels)


async def test_scrape_reports_lag_pending_oldest_idle_and_dead_letters(broker):
    route = _route()
    await broker.ensure_group(route.stream, route.group, start="0")
    for n in range(3):
        await broker.submit(route.stream, {"n": str(n)}, retention=timedelta(hours=1))
    await broker.consume(route.stream, route.group, "c1", count=1, block_ms=100)
    await broker.submit(route.dlq, {"n": "x", "fatal_reason": "boom"}, retention=timedelta(hours=1))
    await asyncio.sleep(0.1)
    registry = _registry(broker, [route])
    labels = {"stream": route.stream, "group": route.group}

    assert await _sample(registry, "agentarea_broker_group_lag", **labels) == 2
    assert await _sample(registry, "agentarea_broker_group_pending", **labels) == 1
    idle = await _sample(registry, "agentarea_broker_group_oldest_pending_seconds", **labels)
    assert idle is not None and idle >= 0.1
    assert await _sample(registry, "agentarea_broker_dlq_length", stream=route.dlq) == 1
    assert await _sample(registry, "agentarea_broker_health_up") == 1


async def test_a_group_not_yet_created_reports_no_group_samples(broker):
    route = _route()
    registry = _registry(broker, [route])

    labels = {"stream": route.stream, "group": route.group}
    assert await _sample(registry, "agentarea_broker_group_lag", **labels) is None
    assert await _sample(registry, "agentarea_broker_dlq_length", stream=route.dlq) == 0
    assert await _sample(registry, "agentarea_broker_health_up") == 1


class _DownBroker:
    async def group_info(self, stream: str, group: str):
        raise ConnectionError("broker down")

    async def length(self, stream: str) -> int:
        raise ConnectionError("broker down")


async def test_an_unreachable_broker_reports_down_instead_of_failing_the_scrape(caplog):
    registry = _registry(_DownBroker(), [_route()])

    assert await _sample(registry, "agentarea_broker_health_up") == 0
    assert any(r.exc_info for r in caplog.records)


async def test_collecting_on_the_event_loop_thread_is_refused():
    collector = BrokerHealthCollector(
        _DownBroker(),  # type: ignore[arg-type]
        [_route()],
        asyncio.get_running_loop(),
        timeout_seconds=5,
    )

    with pytest.raises(RuntimeError, match="event loop"):
        list(collector.collect())


async def test_startup_registers_every_configured_group_and_close_unregisters():
    registry = CollectorRegistry()
    settings = SimpleNamespace(
        broker=RedisSettings(REDIS_URL=REDIS_URL),
        streams=EventStreamSettings(),
    )

    handle = start_broker_health_metrics(settings, registry)  # type: ignore[arg-type]
    names = set(registry._names_to_collectors)
    await handle.aclose()

    assert "agentarea_broker_group_lag" in names
    assert "agentarea_broker_dlq_length" in names
    assert registry._names_to_collectors == {}


async def test_startup_refuses_a_broker_without_consumer_groups_to_read():
    settings = SimpleNamespace(broker=KafkaSettings(), streams=EventStreamSettings())

    with pytest.raises(RuntimeError, match="AGENTAREA_BROKER=redis"):
        start_broker_health_metrics(settings, CollectorRegistry())  # type: ignore[arg-type]
