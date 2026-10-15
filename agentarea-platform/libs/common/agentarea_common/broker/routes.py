"""The consumer groups the platform runs, each with its dead-letter stream, from configuration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agentarea_common.config.channels import ChannelDeliverySettings
from agentarea_common.config.streams import EventStreamSettings

from .topics import STREAM_EVENTS, STREAM_EVENTS_GROUPS, dead_letter_topic, stream_events_partitions


@dataclass(frozen=True)
class ConsumerGroupRoute:
    stream: str
    group: str
    dlq: str


def configured_routes(
    channels: ChannelDeliverySettings, streams: EventStreamSettings
) -> tuple[ConsumerGroupRoute, ...]:
    """Channel groups, then one route per stream-events partition for each of its groups."""
    return (
        ConsumerGroupRoute(stream=channels.IN_STREAM, group=channels.IN_GROUP, dlq=channels.IN_DLQ),
        ConsumerGroupRoute(
            stream=channels.OUT_STREAM, group=channels.OUT_GROUP, dlq=channels.OUT_DLQ
        ),
        *(
            ConsumerGroupRoute(
                stream=partition, group=group, dlq=dead_letter_topic(STREAM_EVENTS, group)
            )
            for group in STREAM_EVENTS_GROUPS
            for partition in stream_events_partitions(streams.PARTITIONS)
        ),
    )


def routes_for_dlq(
    routes: Sequence[ConsumerGroupRoute], dlq: str
) -> tuple[ConsumerGroupRoute, ...]:
    """The routes that dead-letter into `dlq`: one, or one per partition of a partitioned topic."""
    found = tuple(route for route in routes if route.dlq == dlq)
    if not found:
        known = ", ".join(sorted({route.dlq for route in routes}))
        raise LookupError(f"{dlq} is not a configured dead-letter stream (known: {known})")
    return found
