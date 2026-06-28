"""Redis Streams adapter for the event-bus ports (ADR-0018).

Implements ``EventPublisher`` and ``EventSubscriber`` on top of the existing
``BrokerClient`` (``agentarea_common.broker``): XADD to publish, consumer-group
XREADGROUP + XACK to consume, XAUTOCLAIM to redeliver from dead/failed
consumers. Delivery is at-least-once, so handlers must be idempotent.

The ``IntegrationEvent`` is encoded as Redis stream fields in CloudEvents
binary content mode: envelope attributes become ``ce_*`` fields, the payload is
a JSON string under ``data``. This is language-neutral — a Go/other consumer
reads the same fields without any FastStream framing.

``EventStream`` (read side for SSE/A2A) is added in a later increment.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from agentarea_common.broker.interface import BrokerClient, BrokerMessage

from ..ports import Handler, IntegrationEvent, Subscription

logger = logging.getLogger(__name__)

# Stop redelivering a message after this many failed attempts (poison pill).
DEFAULT_MAX_DELIVERY = 5
# Reclaim messages pending longer than this from dead/stuck consumers.
DEFAULT_MIN_IDLE_MS = 60_000


def topic_for(event_type: str) -> str:
    """Map an event type to its stream name. One stream per event type."""
    return f"events:{event_type}"


def _json_default(obj: object) -> str:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def encode(event: IntegrationEvent) -> dict[str, str]:
    """IntegrationEvent -> Redis stream fields (CloudEvents binary mode)."""
    fields: dict[str, str] = {
        "ce_id": str(event.id),
        "ce_type": event.type,
        "ce_source": event.source,
        "ce_time": event.time.isoformat(),
        "ce_specversion": event.specversion,
        "ce_datacontenttype": event.datacontenttype,
        "data": json.dumps(event.data, default=_json_default),
    }
    for key, value in (
        ("ce_subject", event.subject),
        ("ce_correlationid", event.correlation_id),
        ("ce_causationid", event.causation_id),
        ("ce_traceparent", event.traceparent),
    ):
        if value is not None:
            fields[key] = value
    return fields


def decode(fields: dict[str, str]) -> IntegrationEvent:
    """Redis stream fields -> IntegrationEvent."""
    return IntegrationEvent(
        id=UUID(fields["ce_id"]) if "ce_id" in fields else uuid4(),
        type=fields["ce_type"],
        source=fields["ce_source"],
        time=datetime.fromisoformat(fields["ce_time"])
        if "ce_time" in fields
        else datetime.now(UTC),
        specversion=fields.get("ce_specversion", "1.0"),
        datacontenttype=fields.get("ce_datacontenttype", "application/json"),
        subject=fields.get("ce_subject"),
        correlation_id=fields.get("ce_correlationid"),
        causation_id=fields.get("ce_causationid"),
        traceparent=fields.get("ce_traceparent"),
        data=json.loads(fields["data"]) if fields.get("data") else {},
    )


class _StreamSubscription:
    """Running subscription backed by an asyncio consume loop."""

    def __init__(self, task: asyncio.Task[None]) -> None:
        self._task = task

    async def stop(self) -> None:
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass


class RedisStreamsEventBus:
    """``EventPublisher`` + ``EventSubscriber`` over a ``BrokerClient``."""

    def __init__(
        self,
        broker: BrokerClient,
        *,
        consumer: str | None = None,
        max_delivery: int = DEFAULT_MAX_DELIVERY,
        min_idle_ms: int = DEFAULT_MIN_IDLE_MS,
    ) -> None:
        self._broker = broker
        # Unique per process so competing consumers in a group don't collide.
        self._consumer = consumer or f"c-{uuid4().hex[:12]}"
        self._max_delivery = max_delivery
        self._min_idle_ms = min_idle_ms

    async def publish(self, event: IntegrationEvent) -> None:
        await self._broker.submit(topic_for(event.type), encode(event))

    async def subscribe(
        self, *, topic: str, group: str, handler: Handler
    ) -> Subscription:
        stream = topic_for(topic)
        # Create from "$": the group only gets messages published after it
        # exists. Once created the group is durable, so consumer downtime is
        # covered by stream retention + the group's last-delivered cursor.
        await self._broker.ensure_group(stream, group, start="$")
        task = asyncio.create_task(self._run(stream, group, handler))
        return _StreamSubscription(task)

    async def _run(self, stream: str, group: str, handler: Handler) -> None:
        while True:
            try:
                # Reclaim stale messages (failed/crashed consumers) first, then
                # take new ones. Both paths are handled identically.
                reclaimed = await self._broker.autoclaim(
                    stream, group, self._consumer, min_idle_ms=self._min_idle_ms
                )
                for msg in reclaimed:
                    await self._handle(stream, group, msg, handler)

                fresh = await self._broker.consume(
                    stream, group, self._consumer, count=10, block_ms=5000
                )
                for msg in fresh:
                    await self._handle(stream, group, msg, handler)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Event consume loop error on stream %s", stream)
                await asyncio.sleep(1)

    async def _handle(
        self, stream: str, group: str, msg: BrokerMessage, handler: Handler
    ) -> None:
        if msg.delivery_count > self._max_delivery:
            logger.error(
                "Dropping poison message %s on %s after %d deliveries",
                msg.id,
                stream,
                msg.delivery_count,
            )
            await self._broker.ack(stream, group, msg.id)  # give up; remove from PEL
            return
        try:
            event = decode(msg.fields)
        except Exception:
            logger.exception("Undecodable message %s on %s; acking to skip", msg.id, stream)
            await self._broker.ack(stream, group, msg.id)
            return
        try:
            await handler(event)
        except Exception:
            # Do NOT ack — message stays pending and is redelivered via autoclaim.
            logger.exception("Handler failed for %s on %s; will redeliver", msg.id, stream)
            return
        await self._broker.ack(stream, group, msg.id)
