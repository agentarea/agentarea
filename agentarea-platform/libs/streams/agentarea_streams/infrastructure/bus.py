"""Stream events onto the broker: one partition per stream, each event published once.

A stream always lands on the same partition of ``streams.events``, so its order holds.

``DedupCache`` keyed by the deterministic event id stops a repeat at ingest. If
Redis loses it, the repeat passes here and stops at the next key: the events
read model's unique event id, the deterministic task id, the recorded reaction.
"""

from agentarea_common.broker import DedupCache
from agentarea_common.broker.topics import stream_events_partition
from agentarea_common.events.ports import EventPublisher

from ..domain.models import StreamEvent
from .write_quota import WriteQuota


class StreamBus:
    def __init__(
        self,
        *,
        publisher: EventPublisher,
        dedup: DedupCache,
        quota: WriteQuota,
        partitions: int,
    ):
        self._publisher = publisher
        self._dedup = dedup
        self.quota = quota
        self._partitions = partitions

    async def publish(self, event: StreamEvent) -> bool:
        """Publish to the stream's partition; False when the event was published before."""
        key = str(event.id)
        if not await self._dedup.claim(key):
            return False
        try:
            await self._publisher.publish(
                event.to_bus(),
                topic=stream_events_partition(event.stream_id, self._partitions),
            )
        except BaseException:
            # Not on the bus: the sender's retry must be able to publish it.
            await self._dedup.release(key)
            raise
        return True
