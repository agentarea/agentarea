"""Redis Streams adapter for the event-bus ports (ADR-0018).

Implements ``EventPublisher`` and ``EventSubscriber`` on top of the existing
``BrokerClient`` (``agentarea_common.broker``): XADD to publish, consumer-group
XREADGROUP + XACK to consume, XAUTOCLAIM to redeliver from dead/failed
consumers. Delivery is at-least-once, so handlers must be idempotent.

The ``IntegrationEvent`` is encoded as Redis stream fields in CloudEvents
binary content mode: envelope attributes become ``ce_*`` fields, the payload is
a JSON string under ``data``. This is language-neutral — a Go/other consumer
reads the same fields without any FastStream framing.

Two delivery patterns share the same wire format but use different primitives:

- ``RedisStreamsEventBus`` — Competing Consumers (consumer group, ACK, retry,
  at-least-once). For durable work that must be processed exactly once.
- ``RedisStreamsEventStream`` — Publish-Subscribe Channel (broadcast tail, no
  group, no ACK, at-most-once). The CQRS read side: catch-up then live tail.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from agentarea_common.broker.dlq import DEAD_LETTER_REASON_FIELD, DEAD_LETTER_SOURCE_FIELD
from agentarea_common.broker.interface import BrokerClient, BrokerMessage
from agentarea_common.broker.topics import DEAD_LETTER_RETENTION, domain_events_topic
from agentarea_common.observability.propagation import consumer_span, current_traceparent

from ..ports import (
    DeadLetterHandler,
    Handler,
    IntegrationEvent,
    Subscription,
    UnprocessableEventError,
)

logger = logging.getLogger(__name__)

# Stop redelivering a message after this many failed attempts (poison pill).
DEFAULT_MAX_DELIVERY = 5
# Reclaim messages pending longer than this from dead/stuck consumers.
DEFAULT_MIN_IDLE_MS = 60_000
# A consumer idle this long with nothing pending belongs to a stopped process.
STOPPED_CONSUMER_IDLE_MS = 60 * 60 * 1000


_ENVELOPE_FIELDS = frozenset(
    {
        "ce_id",
        "ce_type",
        "ce_source",
        "ce_time",
        "ce_specversion",
        "ce_datacontenttype",
        "ce_subject",
        "ce_correlationid",
        "ce_causationid",
        "ce_traceparent",
        "ce_data",
    }
)
_EXTENSION_NAME = re.compile(r"[a-z0-9]{1,20}")
DEFAULT_BLOCK_MS = 2000


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
    for name, value in event.extensions.items():
        if not _EXTENSION_NAME.fullmatch(name) or f"ce_{name}" in _ENVELOPE_FIELDS:
            raise ValueError(
                f"CloudEvents extension name {name!r} must be lowercase alphanumeric "
                + "and not an envelope attribute"
            )
        fields[f"ce_{name}"] = value
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
        extensions={
            key[3:]: value
            for key, value in fields.items()
            if key.startswith("ce_") and key not in _ENVELOPE_FIELDS
        },
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
            # Expected: awaiting a task we just cancelled re-raises the
            # cancellation here. Swallow it so stop() completes cleanly.
            pass


class RedisStreamsEventBus:
    """``EventPublisher`` + ``EventSubscriber`` over a ``BrokerClient``."""

    def __init__(
        self,
        broker: BrokerClient,
        *,
        retention: timedelta,
        consumer: str | None = None,
        max_delivery: int = DEFAULT_MAX_DELIVERY,
        min_idle_ms: int = DEFAULT_MIN_IDLE_MS,
        block_ms: int = DEFAULT_BLOCK_MS,
    ) -> None:
        self._broker = broker
        self._retention = retention
        # Unique per process so competing consumers in a group don't collide.
        self._consumer = consumer or f"c-{uuid4().hex[:12]}"
        self._max_delivery = max_delivery
        self._min_idle_ms = min_idle_ms
        self._block_ms = block_ms

    async def publish(self, event: IntegrationEvent, *, topic: str | None = None) -> None:
        if event.traceparent is None:
            traceparent = current_traceparent()
            if traceparent is not None:
                event = event.model_copy(update={"traceparent": traceparent})
        await self._broker.submit(
            topic or domain_events_topic(event.type), encode(event), retention=self._retention
        )

    async def subscribe(self, *, topic: str, group: str, handler: Handler) -> Subscription:
        stream = topic
        # Create from "$": the group only gets messages published after it
        # exists. Once created the group is durable, so consumer downtime is
        # covered by stream retention + the group's last-delivered cursor.
        await self._broker.ensure_group(stream, group, start="$")
        task = asyncio.create_task(self._run(stream, group, handler))
        return _StreamSubscription(task)

    async def subscribe_many(
        self,
        *,
        topics: Sequence[str],
        group: str,
        handler: Handler,
        dead_letter_topic: str,
        on_dead_letter: DeadLetterHandler,
    ) -> Subscription:
        dead_letter = _DeadLetter(topic=dead_letter_topic, callback=on_dead_letter)
        streams = list(dict.fromkeys(topics))
        if not streams:
            raise ValueError(f"subscribe_many for group {group} needs at least one topic")
        # From "0": events published before the group first existed are not lost.
        for stream in streams:
            await self._broker.ensure_group(stream, group, start="0")
        task = asyncio.create_task(self._run_many(streams, group, handler, dead_letter))
        return _StreamSubscription(task)

    async def _run_many(
        self, streams: list[str], group: str, handler: Handler, dead_letter: _DeadLetter
    ) -> None:
        loop = asyncio.get_running_loop()
        next_claim = 0.0
        while True:
            try:
                if loop.time() >= next_claim:
                    for stream in streams:
                        reclaimed = await self._broker.autoclaim(
                            stream, group, self._consumer, min_idle_ms=self._min_idle_ms
                        )
                        for msg in reclaimed:
                            await self._handle(stream, group, msg, handler, dead_letter)
                        await self._broker.prune_consumers(
                            stream, group, idle_ms=STOPPED_CONSUMER_IDLE_MS
                        )
                    next_claim = loop.time() + self._min_idle_ms / 1000
                fresh = await self._broker.consume_many(
                    streams, group, self._consumer, count=10, block_ms=self._block_ms
                )
                for msg in fresh:
                    await self._handle(msg.stream, group, msg, handler, dead_letter)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Event consume loop error for group %s", group)
                await asyncio.sleep(1)

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
        self,
        stream: str,
        group: str,
        msg: BrokerMessage,
        handler: Handler,
        dead_letter: _DeadLetter | None = None,
    ) -> None:
        if msg.delivery_count > self._max_delivery:
            if dead_letter is not None:
                await self._dead_letter(stream, group, msg, dead_letter)
                return
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
            if dead_letter is not None:
                logger.exception("Undecodable message %s on %s; dead-lettering it", msg.id, stream)
                await self._submit_dead_letter(dead_letter, stream, msg, "undecodable message")
            else:
                logger.exception("Undecodable message %s on %s; acking to skip", msg.id, stream)
            await self._broker.ack(stream, group, msg.id)
            return
        try:
            with consumer_span(
                traceparent=event.traceparent,
                destination=stream,
                message_id=msg.id,
                consumer_group=group,
            ):
                await handler(event)
        except UnprocessableEventError as unprocessable:
            if dead_letter is None:
                logger.exception("Unprocessable message %s on %s; acking to skip", msg.id, stream)
            else:
                logger.exception(
                    "Unprocessable message %s on %s; dead-lettering it", msg.id, stream
                )
                await self._submit_dead_letter(
                    dead_letter, stream, msg, f"unprocessable: {unprocessable}"
                )
            await self._broker.ack(stream, group, msg.id)
            return
        except Exception:
            # Do NOT ack — message stays pending and is redelivered via autoclaim.
            logger.exception("Handler failed for %s on %s; will redeliver", msg.id, stream)
            return
        await self._broker.ack(stream, group, msg.id)

    async def _dead_letter(
        self, stream: str, group: str, msg: BrokerMessage, dead_letter: _DeadLetter
    ) -> None:
        """Hand the message to the callback, copy it to the dead-letter topic, ack it.

        A callback that fails does not keep the message: it would fail the same
        way on every pass and hold the message pending forever. The dead letter
        records that the callback failed, and a replay runs the message again.
        """
        attempts = msg.delivery_count - 1
        logger.error(
            "Message %s on %s failed %d deliveries; dead-lettering it to %s",
            msg.id,
            stream,
            attempts,
            dead_letter.topic,
        )
        reason = f"max delivery attempts ({attempts}) exceeded"
        try:
            await dead_letter.callback(decode(msg.fields))
        except Exception as error:
            logger.exception("Dead-letter callback failed for %s on %s", msg.id, stream)
            reason = f"{reason}; dead-letter callback failed: {type(error).__name__}: {error}"
        await self._submit_dead_letter(dead_letter, stream, msg, reason)
        await self._broker.ack(stream, group, msg.id)

    async def _submit_dead_letter(
        self, dead_letter: _DeadLetter, stream: str, msg: BrokerMessage, reason: str
    ) -> None:
        await self._broker.submit(
            dead_letter.topic,
            {
                **msg.fields,
                DEAD_LETTER_SOURCE_FIELD: stream,
                DEAD_LETTER_REASON_FIELD: reason[:500],
            },
            retention=DEAD_LETTER_RETENTION,
        )


class _DeadLetter:
    def __init__(self, *, topic: str, callback: DeadLetterHandler) -> None:
        self.topic = topic
        self.callback = callback


class RedisStreamsEventStream:
    """``EventStream`` (CQRS read side) over a ``BrokerClient`` broadcast tail.

    Publish-Subscribe Channel semantics: every reader gets every event
    independently (XREAD, no consumer group, no ACK). ``from_offset="0"``
    replays the stream from the start (catch-up) and then keeps yielding live
    entries; ``"$"`` tails live only. Delivery is at-most-once — suitable for
    ephemeral notifications and live UI tailing, NOT for work that must not be
    lost (use ``RedisStreamsEventBus`` for that).

    Bounded retention is the producer's responsibility (XADD MAXLEN); a reader
    starting from ``"0"`` only sees what retention has kept.
    """

    def __init__(self, broker: BrokerClient, *, block_ms: int = 5000) -> None:
        self._broker = broker
        self._block_ms = block_ms

    async def read(self, *, stream: str, from_offset: str = "0") -> AsyncIterator[IntegrationEvent]:
        cursor = from_offset
        while True:
            cursor, msgs = await self._broker.tail(stream, last_id=cursor, block_ms=self._block_ms)
            for msg in msgs:
                try:
                    yield decode(msg.fields)
                except Exception:
                    logger.exception(
                        "Undecodable stream message %s on %s; skipping", msg.id, stream
                    )
