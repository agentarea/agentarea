"""The consumer groups the platform runs, each with its dead-letter stream, from configuration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agentarea_common.config.streams import EventStreamSettings

from .topics import (
    DELIVERY_GROUP,
    INGEST_GROUP,
    STREAM_EVENTS,
    STREAM_EVENTS_GROUPS,
    STREAMS_INGEST,
    TASK_EVENTS,
    dead_letter_topic,
    stream_events_partitions,
)


@dataclass(frozen=True)
class ConsumerGroupRoute:
    stream: str
    group: str
    dlq: str


def configured_routes(streams: EventStreamSettings) -> tuple[ConsumerGroupRoute, ...]:
    """Polled items to ingest, task-event delivery, then each stream-events partition per group."""
    return (
        ConsumerGroupRoute(
            stream=STREAMS_INGEST,
            group=INGEST_GROUP,
            dlq=dead_letter_topic(STREAMS_INGEST, INGEST_GROUP),
        ),
        ConsumerGroupRoute(
            stream=TASK_EVENTS,
            group=DELIVERY_GROUP,
            dlq=dead_letter_topic(TASK_EVENTS, DELIVERY_GROUP),
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
