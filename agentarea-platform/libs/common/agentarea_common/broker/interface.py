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
    """A message claimed from a broker stream."""

    id: str  # broker-assigned ID (e.g. "1700000000000-0" for Redis Streams)
    fields: dict[str, str]


class BrokerClient(Protocol):
    """Durable stream broker."""

    async def submit(self, stream: str, fields: dict[str, str]) -> str:
        """Append a message to `stream`. Returns the broker-assigned message id."""
        ...

    async def ensure_group(
        self, stream: str, group: str, start: str = "$"
    ) -> None:
        """Create the consumer group + stream if absent. Idempotent."""
        ...

    async def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 5000,
    ) -> list[BrokerMessage]:
        """Claim up to `count` un-ACKed messages for this consumer. Blocks
        up to `block_ms` if the stream is empty. Returns [] on timeout."""
        ...

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        """Mark `message_id` as delivered for `group`. Removes it from PEL."""
        ...

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
        `consumer`)."""
        ...
