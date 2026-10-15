"""Logical broker topic names: ``<domain>.<dataset>``.

The broker adapters put the namespace (``AGENTAREA_EVENT_NAMESPACE``) in front
of every name here, so code never spells it.
"""

from __future__ import annotations

import zlib
from uuid import UUID

STREAM_EVENTS = "streams.events"
TASK_EVENTS = "tasks.events"
DOMAIN_EVENTS = "domain.events"

ROUTER_GROUP = "router"
EVENTS_VIEW_GROUP = "events-view"
STREAM_EVENTS_GROUPS = (ROUTER_GROUP, EVENTS_VIEW_GROUP)


def stream_events_partition(stream_id: UUID, partitions: int) -> str:
    """The partition that carries every event of one stream, so its order holds."""
    return f"{STREAM_EVENTS}.{zlib.crc32(stream_id.bytes) % partitions}"


def stream_events_partitions(partitions: int) -> list[str]:
    return [f"{STREAM_EVENTS}.{n}" for n in range(partitions)]


def dead_letter_topic(topic: str, group: str) -> str:
    return f"{topic}.{group}.dlq"


def task_events_topic(task_id: str) -> str:
    return f"{TASK_EVENTS}.{task_id}"


def domain_events_topic(event_type: str) -> str:
    return f"{DOMAIN_EVENTS}.{event_type}"
