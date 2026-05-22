"""Durable outbound channel delivery on top of Redis Streams.

`ChannelDeliveryEmitter` submits a pre-formatted message to the outbound
stream — that's the producer side, called by `ChannelRouter` instead of
invoking the adapter inline.

`ChannelDeliveryConsumer` is the worker loop: claims via XREADGROUP, dedups,
calls the adapter, and either ACKs (success), leaves un-ACKed (retryable —
broker redelivers after PEL idle), or ACKs into the DLQ stream (fatal).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from .exceptions import ChannelDeliveryError, FatalError, RetryableError

if TYPE_CHECKING:
    from agentarea_common.broker import BrokerClient, DedupCache

    from . import ChannelAdapter

logger = logging.getLogger(__name__)


OUTBOUND_STREAM = "agentarea.channel.outbound"
OUTBOUND_DLQ = "agentarea.channel.outbound.dlq"
OUTBOUND_GROUP = "delivery"


class ChannelDeliveryEmitter:
    """Producer side: submit a delivery job to the outbound stream.

    The router formats and resolves channel_origin, then hands the result
    here. We never block on the actual adapter.send — the worker does it.
    """

    def __init__(self, broker: BrokerClient) -> None:
        self._broker = broker

    async def submit(
        self,
        *,
        channel_type: str,
        channel_config: dict,
        message: str,
        dedup_key: str,
    ) -> str:
        fields = {
            "channel_type": channel_type,
            "channel_config": json.dumps(channel_config),
            "message": message,
            "dedup_key": dedup_key,
        }
        return await self._broker.submit(OUTBOUND_STREAM, fields)


class ChannelDeliveryConsumer:
    """Worker loop: claim outbound stream entries and deliver via adapter.

    On `RetryableError`: leave un-ACKed; broker redelivers after PEL idle
    timeout (configured via XAutoclaimer min_idle_ms upstream). On
    `FatalError` (or unexpected exceptions classified as fatal): ACK and
    DLQ-emit so the message doesn't loop forever.
    """

    def __init__(
        self,
        broker: BrokerClient,
        dedup: DedupCache,
        adapter_resolver,  # Callable[[str], ChannelAdapter | None]
        *,
        consumer_id: str = "c1",
        block_ms: int = 5000,
        batch_size: int = 10,
    ) -> None:
        self._broker = broker
        self._dedup = dedup
        self._resolve_adapter = adapter_resolver
        self._consumer_id = consumer_id
        self._block_ms = block_ms
        self._batch_size = batch_size
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        await self._broker.ensure_group(OUTBOUND_STREAM, OUTBOUND_GROUP, start="0")
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="channel-delivery-consumer")
        logger.info(
            "ChannelDeliveryConsumer started (stream=%s group=%s consumer=%s)",
            OUTBOUND_STREAM,
            OUTBOUND_GROUP,
            self._consumer_id,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("ChannelDeliveryConsumer stopped")

    async def _run_loop(self) -> None:
        backoff = 1.0
        while self._running:
            try:
                msgs = await self._broker.consume(
                    OUTBOUND_STREAM,
                    OUTBOUND_GROUP,
                    self._consumer_id,
                    count=self._batch_size,
                    block_ms=self._block_ms,
                )
                for msg in msgs:
                    await self._handle(msg)
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                if not self._running:
                    break
                logger.error(
                    "ChannelDeliveryConsumer loop error (retry in %.0fs): %s",
                    backoff,
                    exc,
                    exc_info=True,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _handle(self, msg) -> None:
        fields = msg.fields
        dedup_key = fields.get("dedup_key") or msg.id

        # Dedup BEFORE the side effect — duplicates (broker redelivery,
        # autoclaim race) just ACK and return without re-sending.
        if not await self._dedup.claim(dedup_key):
            logger.debug("dedup hit on %s, acking", dedup_key)
            await self._broker.ack(OUTBOUND_STREAM, OUTBOUND_GROUP, msg.id)
            return

        channel_type = fields.get("channel_type", "")
        try:
            channel_config = json.loads(fields.get("channel_config", "{}"))
        except json.JSONDecodeError as exc:
            await self._dead_letter(msg, f"bad channel_config: {exc}")
            return

        message = fields.get("message", "")

        adapter = self._resolve_adapter(channel_type)
        if adapter is None:
            await self._dead_letter(msg, f"no adapter for {channel_type!r}")
            return

        try:
            await adapter.send(channel_config, message)
        except RetryableError as exc:
            logger.warning(
                "delivery retryable %s/%s: %s", channel_type, dedup_key, exc
            )
            return  # no ACK → broker redelivers via PEL idle
        except FatalError as exc:
            await self._dead_letter(msg, f"{type(exc).__name__}: {exc}")
            return
        except ChannelDeliveryError as exc:
            await self._dead_letter(msg, f"{type(exc).__name__}: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            # Unknown errors: classify as retryable. Prefer over-retry over
            # silent loss; XAutoclaimer + PEL delivery_count caps the loop.
            logger.exception("delivery unexpected error on %s", dedup_key)
            _ = exc
            return

        await self._broker.ack(OUTBOUND_STREAM, OUTBOUND_GROUP, msg.id)
        logger.debug("delivered %s/%s", channel_type, dedup_key)

    async def _dead_letter(self, msg, reason: str) -> None:
        dlq_fields = {**msg.fields, "fatal_reason": reason[:500]}
        try:
            await self._broker.submit(OUTBOUND_DLQ, dlq_fields)
        except Exception:  # noqa: BLE001
            logger.exception("failed to write to DLQ for %s", msg.id)
        await self._broker.ack(OUTBOUND_STREAM, OUTBOUND_GROUP, msg.id)
        logger.error("channel delivery DLQ'd: %s (reason=%s)", msg.id, reason)
