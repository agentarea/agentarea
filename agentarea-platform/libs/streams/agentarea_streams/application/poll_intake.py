"""Items the Go event-service polled, into their source's stream (ADR-0040 §3).

Go publishes each raw item, or a gap, to ``streams.ingest``; the ``ingest``
group here runs it through the same ingest as a webhook request: the source's
catalog entry names and keys it, and the event id dedups a repeat. A message is
acknowledged once its event is on the bus. A failure leaves it pending for the
autoclaimer; past ``max_delivery_attempts``, or when it can never succeed (a
malformed message, a source type the catalog does not have), it goes to the
dead-letter topic.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from agentarea_common.base.tenant_scope import unscoped
from agentarea_common.broker import BrokerClient, BrokerMessage
from agentarea_common.broker.dlq import DEAD_LETTER_REASON_FIELD
from agentarea_common.broker.topics import (
    DEAD_LETTER_RETENTION,
    INGEST_GROUP,
    STREAMS_INGEST,
    dead_letter_topic,
)
from agentarea_common.observability.propagation import consumer_span
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.errors import StreamNotFoundError
from ..domain.models import AppendResult
from ..domain.source_types import SourceTypeEntry
from ..infrastructure.catalog_source_types import CatalogSourceTypeRepository
from ..infrastructure.orm import StreamSourceORM

logger = logging.getLogger(__name__)

#: The kind of the event a gap becomes.
GAP_KIND = "source.gap"
ITEM = "item"
GAP = "gap"


class Ingest(Protocol):
    """``source_intake.ingest_source_event``: one event of a source onto the bus."""

    def __call__(
        self,
        session: AsyncSession,
        source: StreamSourceORM,
        entry: SourceTypeEntry,
        *,
        body: Any,
        headers: dict[str, str],
        received_at: datetime,
        kind_override: str | None = None,
        key_override: str | None = None,
    ) -> Awaitable[AppendResult]: ...


async def catalog_entry(session: AsyncSession, slug: str) -> SourceTypeEntry | None:
    return await CatalogSourceTypeRepository(session).get(slug)


class MalformedItemError(ValueError):
    """A message that can never be ingested, however often it is delivered."""


@dataclass(frozen=True)
class PolledItem:
    source_id: UUID
    kind: str
    body: Any
    received_at: datetime
    traceparent: str | None


def parse_message(fields: dict[str, str]) -> PolledItem:
    try:
        source_id = UUID(fields["source_id"])
    except (KeyError, ValueError) as exc:
        raise MalformedItemError("no source_id, or not a uuid") from exc
    kind = fields.get("kind")
    if kind not in (ITEM, GAP):
        raise MalformedItemError(f"kind {kind!r} is neither {ITEM!r} nor {GAP!r}")
    try:
        body = json.loads(fields["item"])
    except (KeyError, json.JSONDecodeError) as exc:
        raise MalformedItemError("no item, or not JSON") from exc
    try:
        received_at = datetime.fromisoformat(fields["received_at"])
    except (KeyError, ValueError) as exc:
        raise MalformedItemError("no received_at, or not an ISO time") from exc
    if received_at.tzinfo is None:
        raise MalformedItemError("received_at has no time zone")
    if kind == GAP and not (isinstance(body, dict) and isinstance(body.get("reason"), str)):
        raise MalformedItemError("a gap names no reason")
    return PolledItem(
        source_id=source_id,
        kind=kind,
        body=body,
        received_at=received_at,
        traceparent=fields.get("traceparent"),
    )


class PolledItemConsumer:
    """The ``ingest`` group on ``streams.ingest``."""

    def __init__(
        self,
        broker: BrokerClient,
        *,
        session_scope: Callable[[], AbstractAsyncContextManager[AsyncSession]],
        ingest: Ingest,
        consumer_id: str,
        load_entry: Callable[
            [AsyncSession, str], Awaitable[SourceTypeEntry | None]
        ] = catalog_entry,
        block_ms: int = 5000,
        batch_size: int = 10,
        max_delivery_attempts: int = 20,
    ) -> None:
        self._broker = broker
        self._session_scope = session_scope
        self._ingest = ingest
        self._load_entry = load_entry
        self._consumer_id = consumer_id
        self._block_ms = block_ms
        self._batch_size = batch_size
        self._max_delivery_attempts = max_delivery_attempts
        self.stream = STREAMS_INGEST
        self.group = INGEST_GROUP
        self.dlq = dead_letter_topic(STREAMS_INGEST, INGEST_GROUP)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        await self._broker.ensure_group(self.stream, self.group, start="0")
        self._task = asyncio.create_task(self._run(), name=f"consume:{self.stream}")
        logger.info("PolledItemConsumer started (consumer=%s)", self._consumer_id)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        backoff = 1.0
        while True:
            try:
                await self.consume_once()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("streams.ingest consume failed (retry in %.0fs)", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def consume_once(self) -> int:
        messages = await self._broker.consume(
            self.stream,
            self.group,
            self._consumer_id,
            count=self._batch_size,
            block_ms=self._block_ms,
        )
        for message in messages:
            await self.handle(message)
        return len(messages)

    async def handle(self, msg: BrokerMessage) -> None:
        if msg.delivery_count > self._max_delivery_attempts:
            await self._dead_letter(msg, f"gave up after {msg.delivery_count} deliveries")
            return
        try:
            item = parse_message(msg.fields)
        except MalformedItemError as exc:
            await self._dead_letter(msg, f"malformed: {exc}")
            return
        with consumer_span(
            traceparent=item.traceparent,
            destination=self.stream,
            message_id=msg.id,
            consumer_group=self.group,
        ):
            try:
                await self._ingest_item(item)
            except MalformedItemError as exc:
                await self._dead_letter(msg, str(exc))
                return
            except Exception:
                # Left pending: the autoclaimer hands it back, and the delivery
                # cap dead-letters it if it never succeeds.
                logger.exception(
                    "polled %s of source %s could not be ingested", item.kind, item.source_id
                )
                return
        await self._broker.ack(self.stream, self.group, msg.id)

    async def _ingest_item(self, item: PolledItem) -> None:
        async with self._session_scope() as session:
            with unscoped("a polled item names its source; the source's workspace owns it"):
                source = await session.get(StreamSourceORM, item.source_id)
            if source is None:
                logger.info("polled item of deleted source %s dropped", item.source_id)
                return
            if not source.webhook_type:
                raise MalformedItemError(f"source {source.id} names no source type")
            entry = await self._load_entry(session, source.webhook_type)
            if entry is None:
                raise MalformedItemError(
                    f"source type {source.webhook_type!r} is not in the catalog"
                )
            gap = item.kind == GAP
            try:
                result = await self._ingest(
                    session,
                    source,
                    entry,
                    body=item.body,
                    headers={},
                    received_at=item.received_at,
                    kind_override=GAP_KIND if gap else None,
                    key_override=f"gap:{item.received_at.isoformat()}" if gap else None,
                )
            except StreamNotFoundError:
                logger.info("polled item of source %s: its stream is gone; dropped", source.id)
                return
        if gap:
            logger.warning("source %s reported a gap: %s", source.id, item.body["reason"])
        elif not result.appended:
            logger.debug("polled item of source %s was a repeat of %s", source.id, result.event_id)

    async def _dead_letter(self, msg: BrokerMessage, reason: str) -> None:
        # A dead letter that was not written must not be acknowledged: it stays
        # pending and comes back here.
        await self._broker.submit(
            self.dlq,
            {**msg.fields, DEAD_LETTER_REASON_FIELD: reason[:500]},
            retention=DEAD_LETTER_RETENTION,
        )
        await self._broker.ack(self.stream, self.group, msg.id)
        logger.error("polled item %s dead-lettered: %s", msg.id, reason)
