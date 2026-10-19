"""Logical broker topic names: ``<domain>.<dataset>``.

The broker adapters put the namespace (``AGENTAREA_EVENT_NAMESPACE``) in front
of every name here, so code never spells it.
"""

from __future__ import annotations

import zlib
from datetime import timedelta
from uuid import UUID

STREAM_EVENTS = "streams.events"
# Raw items the Go event-service polled, one per message, for ingest to name and key.
STREAMS_INGEST = "streams.ingest"
# Every task's events, keyed by task id (the envelope's subject).
TASK_EVENTS = "tasks.events"
# Pub/sub, never kept: a task's live-only signals (a call started, reply chunks, progress).
TASK_LIVE = "tasks.live"
# Pub/sub, never kept: an event of a workspace arrived or moved on, for its open events pages.
STREAMS_LIVE = "streams.live"
DOMAIN_EVENTS = "domain.events"
# Stream events the router matched to an EXTERNAL (MCP Events webhook) subscriber,
# one message per (event, subscriber), for Delivery to send.
EXTERNAL_EVENTS = "streams.external"

ROUTER_GROUP = "router"
EVENTS_VIEW_GROUP = "events-view"
STREAM_EVENTS_GROUPS = (ROUTER_GROUP, EVENTS_VIEW_GROUP)
DELIVERY_GROUP = "delivery"
# Projects task outcomes into each workspace's platform stream.
PLATFORM_GROUP = "platform"
INGEST_GROUP = "ingest"

# How long the broker keeps a topic's entries: enough to ride out a consumer
# outage. History is Postgres's job (the task log, the events read model).
BUS_RETENTION = timedelta(hours=72)
# Dead letters wait for an operator longer than live traffic does.
DEAD_LETTER_RETENTION = timedelta(days=14)


def stream_events_partition(stream_id: UUID, partitions: int) -> str:
    """The partition that carries every event of one stream, so its order holds."""
    return f"{STREAM_EVENTS}.{zlib.crc32(stream_id.bytes) % partitions}"


def stream_events_partitions(partitions: int) -> list[str]:
    return [f"{STREAM_EVENTS}.{n}" for n in range(partitions)]


def dead_letter_topic(topic: str, group: str) -> str:
    return f"{topic}.{group}.dlq"


def task_live_channel(task_id: str) -> str:
    return f"{TASK_LIVE}.{task_id}"


def streams_live_channel(workspace_id: str) -> str:
    return f"{STREAMS_LIVE}.{workspace_id}"


def domain_events_topic(event_type: str) -> str:
    return f"{DOMAIN_EVENTS}.{event_type}"


def external_retry_topic(attempt: int) -> str:
    """Where a webhook delivery waits for its ``attempt``-th retry; one delay per topic."""
    return f"{EXTERNAL_EVENTS}.retry.{attempt}"
