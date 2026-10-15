"""Broker-agnostic interface for durable streams.

The OSS deployment uses Redis Streams. Enterprise can swap in Kafka behind
the same Protocol — `submit / ensure_group / consume / ack / autoclaim`.
Dedup is consumer-side responsibility (see `DedupCache`) so it survives a
broker swap without leaking broker-specific ID schemes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class BrokerMessage:
    """A message claimed from a broker stream.

    `delivery_count` is the universal "how many times has this message
    been handed to a consumer" counter. The shape is broker-agnostic — each
    BrokerClient impl populates it from its native primitive:

      - Redis Streams: XPENDING ... delivery_count
      - NATS JetStream: msg.metadata.num_delivered
      - AWS SQS: ApproximateReceiveCount
      - Kafka (no native): broker maintains a side counter

    Consumers use `delivery_count` to cap poison loops and dead-letter
    messages that have failed too many times, without knowing or caring
    which broker is underneath.
    """

    id: str  # broker-assigned ID (e.g. "1700000000000-0" for Redis Streams)
    fields: dict[str, str]
    delivery_count: int = 1
    # The stream it was read from; set by reads that span several streams.
    stream: str = ""


@dataclass(frozen=True)
class GroupInfo:
    """A consumer group's position on its stream."""

    lag: int  # entries in the stream not yet delivered to the group
    consumers: int
    last_delivered_id: str


@dataclass(frozen=True)
class PendingSummary:
    """Messages delivered to a group and not yet acknowledged."""

    count: int
    oldest_idle_ms: int | None  # longest time since delivery; None when nothing is pending


class BrokerClient(Protocol):
    """Durable stream broker."""

    async def submit(
        self,
        stream: str,
        fields: dict[str, str],
        *,
        maxlen: int | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        """Append a message to `stream`. Returns the broker-assigned message id.

        `maxlen` caps stream length with approximate trimming (the channel's
        retention policy for bounded buffers, e.g. live-tail streams). `None`
        leaves the stream unbounded (durable log). `ttl_seconds` expires the
        whole stream that long after its latest append; `None` never expires it.
        """
        raise NotImplementedError

    async def ensure_group(self, stream: str, group: str, start: str = "$") -> None:
        """Create the consumer group + stream if absent. Idempotent."""
        raise NotImplementedError

    async def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 5000,
    ) -> list[BrokerMessage]:
        """Claim up to `count` un-ACKed messages for this consumer. Blocks
        up to `block_ms` if the stream is empty. Returns [] on timeout.
        """
        raise NotImplementedError

    async def consume_many(
        self,
        streams: list[str],
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 5000,
    ) -> list[BrokerMessage]:
        """``consume`` over several streams in one call, each message naming its stream.

        Every stream must already have ``group``.
        """
        raise NotImplementedError

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        """Mark `message_id` as delivered for `group`. Removes it from PEL."""
        raise NotImplementedError

    async def autoclaim(
        self,
        stream: str,
        group: str,
        consumer: str,
        min_idle_ms: int,
        start: str = "0-0",
        count: int = 100,
    ) -> list[BrokerMessage]:
        """Reclaim messages that have been pending longer than `min_idle_ms`
        from dead consumers. Returns the reclaimed batch (now owned by
        `consumer`).
        """
        raise NotImplementedError

    async def tail(
        self,
        stream: str,
        last_id: str = "$",
        block_ms: int = 5000,
        count: int = 100,
    ) -> tuple[str, list[BrokerMessage]]:
        """Broadcast read with NO consumer group (Publish-Subscribe Channel).

        Every reader sees every message independently — there is no group,
        no ACK, and no pending-entries list. Used for the CQRS read side
        (live tailing) where delivery is fan-out and at-most-once.

        `last_id` is an opaque cursor: ``"$"`` yields only entries appended
        after this call (live only); ``"0"`` yields from the start of the
        stream (catch-up). Returns ``(next_cursor, messages)``; pass
        `next_cursor` back to continue. On block timeout returns
        ``(last_id, [])`` unchanged.
        """
        raise NotImplementedError

    async def group_info(self, stream: str, group: str) -> GroupInfo | None:
        """The group's lag and consumers, or None when the stream or group does not exist."""
        raise NotImplementedError

    async def pending_summary(self, stream: str, group: str) -> PendingSummary:
        """How many messages the group holds un-ACKed and the longest one has waited."""
        raise NotImplementedError

    async def length(self, stream: str) -> int:
        """Entries currently kept in `stream`; 0 when it does not exist."""
        raise NotImplementedError

    async def read_range(
        self, stream: str, start: str = "-", end: str = "+", count: int = 100
    ) -> list[BrokerMessage]:
        """Up to `count` entries with ids in [`start`, `end`], oldest first.

        ``"-"`` and ``"+"`` are the stream's ends; a ``"("`` prefix makes a bound
        exclusive. No group, no ACK.
        """
        raise NotImplementedError

    async def move(
        self, source: str, message_id: str, target: str, fields: dict[str, str]
    ) -> str | None:
        """Append `fields` to `target` and remove `message_id` from `source`, atomically.

        Returns the new id, or None when `message_id` is no longer in `source`
        (already moved), in which case nothing is appended.
        """
        raise NotImplementedError
