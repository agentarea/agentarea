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


class BrokerClient(Protocol):
    """Durable stream broker."""

    async def submit(self, stream: str, fields: dict[str, str]) -> str:
        """Append a message to `stream`. Returns the broker-assigned message id."""
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
