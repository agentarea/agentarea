"""Consumer-group health as Prometheus gauges, read from the broker on each scrape.

The collector sits on the default registry next to the API's other metrics. A
scrape runs on the metrics server's thread and reads the broker on the event
loop that owns the broker connection, so there is no polling loop and the
numbers are as fresh as the scrape.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from prometheus_client import REGISTRY, CollectorRegistry
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

from agentarea_common.broker.interface import BrokerClient, GroupInfo, PendingSummary
from agentarea_common.broker.redis_streams import RedisStreamsBroker
from agentarea_common.broker.routes import ConsumerGroupRoute, configured_routes
from agentarea_common.config.broker import RedisSettings
from agentarea_common.config.settings import Settings

logger = logging.getLogger(__name__)

SCRAPE_TIMEOUT_SECONDS = 5.0

_GROUP_LABELS = ["stream", "group"]


@dataclass(frozen=True)
class GroupHealth:
    route: ConsumerGroupRoute
    info: GroupInfo
    pending: PendingSummary


@dataclass(frozen=True)
class BrokerHealth:
    groups: tuple[GroupHealth, ...]
    dead_letters: dict[str, int]


async def read_broker_health(
    broker: BrokerClient, routes: Sequence[ConsumerGroupRoute]
) -> BrokerHealth:
    """Each existing group's lag and pending entries, and each dead-letter stream's length.

    A group whose consumer has not started yet has no position to report and is left out.
    """
    groups: list[GroupHealth] = []
    for route in routes:
        info = await broker.group_info(route.stream, route.group)
        if info is None:
            continue
        pending = await broker.pending_summary(route.stream, route.group)
        groups.append(GroupHealth(route=route, info=info, pending=pending))
    dead_letters = {dlq: await broker.length(dlq) for dlq in dict.fromkeys(r.dlq for r in routes)}
    return BrokerHealth(groups=tuple(groups), dead_letters=dead_letters)


def _families() -> tuple[GaugeMetricFamily, ...]:
    return (
        GaugeMetricFamily(
            "agentarea_broker_group_lag",
            "Entries in the stream not yet delivered to the consumer group.",
            labels=_GROUP_LABELS,
        ),
        GaugeMetricFamily(
            "agentarea_broker_group_pending",
            "Entries delivered to the consumer group and not yet acknowledged.",
            labels=_GROUP_LABELS,
        ),
        GaugeMetricFamily(
            "agentarea_broker_group_oldest_pending_seconds",
            "Longest time a pending entry of the consumer group has waited since delivery.",
            labels=_GROUP_LABELS,
        ),
        GaugeMetricFamily(
            "agentarea_broker_dlq_length",
            "Entries in the dead-letter stream.",
            labels=["stream"],
        ),
        GaugeMetricFamily(
            "agentarea_broker_health_up",
            "1 when the last scrape read consumer-group health from the broker, else 0.",
        ),
    )


class BrokerHealthCollector(Collector):
    def __init__(
        self,
        broker: BrokerClient,
        routes: Sequence[ConsumerGroupRoute],
        loop: asyncio.AbstractEventLoop,
        *,
        timeout_seconds: float,
    ) -> None:
        self._broker = broker
        self._routes = tuple(routes)
        self._loop = loop
        self._timeout = timeout_seconds

    def describe(self) -> Iterator[GaugeMetricFamily]:
        return iter(_families())

    def collect(self) -> Iterator[GaugeMetricFamily]:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            raise RuntimeError(
                "BrokerHealthCollector reads on its event loop and cannot be collected from it"
            )
        lag, pending, oldest, dlq, up = _families()
        future = asyncio.run_coroutine_threadsafe(
            read_broker_health(self._broker, self._routes), self._loop
        )
        try:
            health = future.result(self._timeout)
        except Exception:
            future.cancel()
            logger.exception("Reading consumer-group health from the broker failed")
            up.add_metric([], 0)
            yield up
            return
        for group in health.groups:
            labels = [group.route.stream, group.route.group]
            lag.add_metric(labels, group.info.lag)
            pending.add_metric(labels, group.pending.count)
            oldest.add_metric(labels, (group.pending.oldest_idle_ms or 0) / 1000)
        for stream, length in health.dead_letters.items():
            dlq.add_metric([stream], length)
        up.add_metric([], 1)
        yield from (lag, pending, oldest, dlq, up)


class BrokerHealthMetrics:
    """The registered collector and the broker connection it reads through."""

    def __init__(
        self,
        broker: RedisStreamsBroker,
        collector: BrokerHealthCollector,
        registry: CollectorRegistry,
    ) -> None:
        self._broker = broker
        self._collector = collector
        self._registry = registry

    async def aclose(self) -> None:
        self._registry.unregister(self._collector)
        await self._broker.aclose()


def start_broker_health_metrics(
    settings: Settings, registry: CollectorRegistry = REGISTRY
) -> BrokerHealthMetrics:
    """Register consumer-group health for every configured group. Call on the serving loop."""
    if not isinstance(settings.broker, RedisSettings):
        current = settings.broker.BROKER
        raise RuntimeError(
            f"Broker health metrics need AGENTAREA_BROKER=redis (current: {current})"
        )
    broker = RedisStreamsBroker(settings.broker.REDIS_URL, namespace=settings.streams.NAMESPACE)
    collector = BrokerHealthCollector(
        broker,
        configured_routes(settings.channel_delivery, settings.streams),
        asyncio.get_running_loop(),
        timeout_seconds=SCRAPE_TIMEOUT_SECONDS,
    )
    registry.register(collector)
    return BrokerHealthMetrics(broker, collector, registry)
