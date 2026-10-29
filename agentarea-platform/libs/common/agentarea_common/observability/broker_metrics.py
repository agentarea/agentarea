"""Consumer-group health as observable gauges, read from the broker on each collection.

The exporter collects on its own thread and reads the broker on the event loop
that owns the broker connection, so there is no polling loop and the numbers
are as fresh as the collection. One read serves every gauge of a collection.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from threading import Lock

from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Observation

from agentarea_common.broker.interface import BrokerClient, GroupInfo, PendingSummary
from agentarea_common.broker.redis_streams import RedisStreamsBroker
from agentarea_common.broker.routes import ConsumerGroupRoute, configured_routes
from agentarea_common.config.broker import RedisSettings
from agentarea_common.config.settings import Settings

logger = logging.getLogger(__name__)

READ_TIMEOUT_SECONDS = 5.0
# The gauges of one collection are observed one after another; they share a read.
_READ_REUSE_SECONDS = 1.0


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


def broker_observations(health: BrokerHealth | None) -> dict[str, list[Observation]]:
    """What each gauge reports for one read; ``None`` is a read that failed."""
    if health is None:
        return {"agentarea.broker.health": [Observation(0)]}
    lag, pending, oldest = [], [], []
    for group in health.groups:
        labels = {"stream": group.route.stream, "group": group.route.group}
        lag.append(Observation(group.info.lag, labels))
        pending.append(Observation(group.pending.count, labels))
        oldest.append(Observation((group.pending.oldest_age_ms or 0) / 1000, labels))
    return {
        "agentarea.broker.group.lag": lag,
        "agentarea.broker.group.pending": pending,
        "agentarea.broker.group.oldest_pending": oldest,
        "agentarea.broker.dlq.length": [
            Observation(length, {"stream": stream})
            for stream, length in health.dead_letters.items()
        ],
        "agentarea.broker.health": [Observation(1)],
    }


class BrokerHealthReader:
    """Reads consumer-group health on the broker's loop from the exporter's thread."""

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
        self._lock = Lock()
        self._read_at: float | None = None
        self._observations: dict[str, list[Observation]] = {}

    def observations(self, name: str) -> list[Observation]:
        with self._lock:
            if self._read_at is None or time.monotonic() - self._read_at > _READ_REUSE_SECONDS:
                self._observations = broker_observations(self._read())
                self._read_at = time.monotonic()
            return self._observations.get(name, [])

    def _read(self) -> BrokerHealth | None:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            logger.error("Broker health cannot be read from the broker's own event loop")
            return None
        if self._loop.is_closed():
            logger.warning("Broker health cannot be read: the broker's event loop is closed")
            return None
        read = read_broker_health(self._broker, self._routes)
        future = None
        try:
            future = asyncio.run_coroutine_threadsafe(read, self._loop)
            return future.result(self._timeout)
        except Exception:
            if future is None:
                read.close()
            else:
                future.cancel()
            logger.warning("Reading consumer-group health from the broker failed", exc_info=True)
            return None


_active: BrokerHealthReader | None = None


def _gauge(name: str):
    def observe(_options: CallbackOptions) -> Iterable[Observation]:
        reader = _active
        return reader.observations(name) if reader is not None else []

    return observe


_meter = metrics.get_meter("agentarea.broker")
_meter.create_observable_gauge(
    "agentarea.broker.group.lag",
    callbacks=[_gauge("agentarea.broker.group.lag")],
    unit="{entry}",
    description="Entries in the stream not yet delivered to the consumer group.",
)
_meter.create_observable_gauge(
    "agentarea.broker.group.pending",
    callbacks=[_gauge("agentarea.broker.group.pending")],
    unit="{entry}",
    description="Entries delivered to the consumer group and not yet acknowledged.",
)
_meter.create_observable_gauge(
    "agentarea.broker.group.oldest_pending",
    callbacks=[_gauge("agentarea.broker.group.oldest_pending")],
    unit="s",
    description="Age of the oldest entry the consumer group holds pending; a redelivery does not reset it.",
)
_meter.create_observable_gauge(
    "agentarea.broker.dlq.length",
    callbacks=[_gauge("agentarea.broker.dlq.length")],
    unit="{entry}",
    description="Entries in the dead-letter stream.",
)
_meter.create_observable_gauge(
    "agentarea.broker.health",
    callbacks=[_gauge("agentarea.broker.health")],
    description="1 when the last collection read consumer-group health from the broker, else 0.",
)


class BrokerHealthMetrics:
    """The active reader and the broker connection it reads through."""

    def __init__(self, broker: RedisStreamsBroker, reader: BrokerHealthReader) -> None:
        self._broker = broker
        self._reader = reader

    async def aclose(self) -> None:
        global _active
        if _active is self._reader:
            _active = None
        await self._broker.aclose()


def start_broker_health_metrics(settings: Settings) -> BrokerHealthMetrics | None:
    """Report consumer-group health for every configured group. Call on the serving loop.

    None for a broker whose consumer groups these gauges cannot read (Kafka).
    """
    global _active
    if not isinstance(settings.broker, RedisSettings):
        logger.warning(
            "Broker gauges are unavailable for AGENTAREA_BROKER=%s; "
            "consumer-group health is reported for redis only",
            settings.broker.BROKER,
        )
        return None
    broker = RedisStreamsBroker(settings.broker.REDIS_URL, namespace=settings.streams.NAMESPACE)
    reader = BrokerHealthReader(
        broker,
        configured_routes(settings.streams),
        asyncio.get_running_loop(),
        timeout_seconds=READ_TIMEOUT_SECONDS,
    )
    _active = reader
    return BrokerHealthMetrics(broker, reader)
