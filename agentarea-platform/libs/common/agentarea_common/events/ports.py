"""Event-bus ports — broker-neutral abstractions (ADR-0018).

Application and domain code depend on these Protocols; infrastructure adapters
(Redis Streams now, Kafka/NATS later) implement them. Nothing here knows about a
specific broker, FastStream, or a serialization format — that lives in adapters.

Three ports, split by responsibility (ISP):

- ``EventPublisher``  — write side: emit an integration event.
- ``EventSubscriber`` — choreography: durable consumer-group subscription with
  at-least-once delivery; handlers must be idempotent.
- ``EventStream``     — read side (CQRS): catch-up replay from an offset then
  live tail, for SSE / A2A / projections.

The wire contract is the ``IntegrationEvent`` envelope (CloudEvents-aligned).
Today ``data`` is a JSON-friendly mapping (structured content mode); when the
Protobuf contract lands, payloads move to binary content mode (proto bytes in
the transport body, these attributes in headers) — an adapter concern that does
not change this interface.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class IntegrationEvent(BaseModel):
    """Cross-boundary event contract (CloudEvents 1.0 attribute names).

    ``type`` is the versioned, context-owned event name, e.g.
    ``agentarea.agents.v1.AgentDeleted``. ``subject`` carries the aggregate id
    and doubles as the partition/ordering key — the one thing that cannot be
    abstracted across brokers (Redis orders per-stream, Kafka per-partition), so
    handlers must be idempotent and order-tolerant.
    """

    id: UUID = Field(default_factory=uuid4)
    type: str
    source: str
    time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    specversion: str = "1.0"
    datacontenttype: str = "application/json"
    subject: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    traceparent: str | None = None  # W3C trace context
    data: dict[str, Any] = Field(default_factory=dict)
    # CloudEvents extension attributes: lowercase alphanumeric names, string values.
    extensions: dict[str, str] = Field(default_factory=dict)

    @property
    def partition_key(self) -> str:
        """Key used for ordering/partitioning; falls back to event id."""
        return self.subject or str(self.id)


# A consumer callback. Raising propagates to the adapter, which must NOT ack the
# message (so it is redelivered) — at-least-once delivery.
Handler = Callable[[IntegrationEvent], Awaitable[None]]


@runtime_checkable
class Subscription(Protocol):
    """Handle to a running subscription."""

    async def stop(self) -> None:
        raise NotImplementedError


@runtime_checkable
class EventPublisher(Protocol):
    """Write side: publish an integration event to its topic.

    The topic defaults to ``domain.events.{type}``; a caller that routes by
    something else (a stream's ``streams.events.{partition}``) names it.
    """

    async def publish(self, event: IntegrationEvent, *, topic: str | None = None) -> None:
        raise NotImplementedError


@runtime_checkable
class EventSubscriber(Protocol):
    """Choreography: durable, at-least-once consumer-group subscription.

    ``group`` is the consumer group (competing consumers share one group);
    ``handler`` must be idempotent because delivery is at-least-once.
    """

    async def subscribe(self, *, topic: str, group: str, handler: Handler) -> Subscription:
        raise NotImplementedError


# Called once for a message that failed past the delivery limit, before it is
# moved to the dead-letter topic and acknowledged. Raising keeps it pending.
DeadLetterHandler = Callable[[IntegrationEvent], Awaitable[None]]


@runtime_checkable
class EventGroupSubscriber(Protocol):
    """One consumer group over a fixed set of topics (the partitions of one topic).

    The group starts at each topic's first event. A message delivered
    ``max_delivery`` times without success goes to ``on_dead_letter``, then to
    ``dead_letter_topic`` naming the topic it came from, and is acknowledged.
    """

    async def subscribe_many(
        self,
        *,
        topics: Sequence[str],
        group: str,
        handler: Handler,
        dead_letter_topic: str,
        on_dead_letter: DeadLetterHandler,
    ) -> Subscription:
        raise NotImplementedError


@runtime_checkable
class EventStream(Protocol):
    """Read side (CQRS): catch-up then live tail over a durable log.

    ``from_offset`` is an opaque, adapter-defined cursor (``"0"`` = from the
    beginning for full replay; an adapter may accept a last-seen id to resume).
    Yields events in append order and keeps yielding live ones — solves the
    "subscriber attached after start, lost early events" race without polling.
    """

    def read(self, *, stream: str, from_offset: str = "0") -> AsyncIterator[IntegrationEvent]:
        raise NotImplementedError
