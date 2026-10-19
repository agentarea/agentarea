"""Composition for event streams: the bus every stream writer publishes to."""

import logging
from dataclasses import dataclass

from agentarea_common.broker import DedupCache, RedisStreamsBroker
from agentarea_common.config import RedisSettings, Settings
from agentarea_common.di.container import register_singleton
from agentarea_common.events.adapters.redis_streams import RedisStreamsEventBus

from .bus import StreamBus
from .write_quota import WriteQuota

logger = logging.getLogger(__name__)


@dataclass
class StreamBusResources:
    """The bus and the connections behind it; whoever set it up closes them."""

    bus: StreamBus
    broker: RedisStreamsBroker
    events: RedisStreamsEventBus
    dedup: DedupCache
    quota: WriteQuota

    async def aclose(self) -> None:
        await self.dedup.aclose()
        await self.quota.aclose()
        await self.broker.aclose()


def build_stream_bus(settings: Settings) -> StreamBusResources:
    if not isinstance(settings.broker, RedisSettings):
        raise RuntimeError(
            "Event streams are carried by the Redis broker; set AGENTAREA_BROKER=redis "
            + f"(current: {settings.broker.BROKER})"
        )
    namespace = settings.streams.NAMESPACE
    broker = RedisStreamsBroker(settings.broker.REDIS_URL, namespace=namespace)
    events = RedisStreamsEventBus(
        broker, retention=settings.streams.RETENTION, max_delivery=settings.streams.MAX_ATTEMPTS
    )
    dedup = DedupCache(settings.broker.REDIS_URL, namespace=namespace, prefix="stream-event")
    quota = WriteQuota(settings.broker.REDIS_URL, namespace=namespace)
    bus = StreamBus(
        publisher=events, dedup=dedup, quota=quota, partitions=settings.streams.PARTITIONS
    )
    return StreamBusResources(bus=bus, broker=broker, events=events, dedup=dedup, quota=quota)


def setup_streams_di(settings: Settings) -> StreamBusResources:
    """Register the bus; the caller owns the resources and closes them on shutdown."""
    resources = build_stream_bus(settings)
    register_singleton(StreamBus, resources.bus)
    logger.info("StreamBus=RedisStreamsEventBus")
    return resources
