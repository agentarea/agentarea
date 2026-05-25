"""Durable outbound channel delivery on top of a `BrokerClient`.

`ChannelDeliveryEmitter` is the producer side: it takes the formatted
message + channel config from `ChannelRouter` and writes it onto the
outbound stream.

`ChannelDeliveryConsumer` is the worker loop: claim via the broker,
dedup, call the adapter, then ACK / requeue / DLQ depending on the
typed outcome.

Stream / group names are constructor params, never module globals, so
tests construct their own isolated streams and production wires the
defaults from `apps/worker/main.py`.
"""

from __future__ import annotations

import asyncio
import json
import logging

from agentarea_common.broker import BrokerClient, BrokerMessage, DedupCache

from .exceptions import ChannelDeliveryError, FatalError, RetryableError

logger = logging.getLogger(__name__)


class ChannelDeliveryEmitter:
    """Producer side: submit a delivery job to the outbound stream.

    `stream` is mandatory — it comes from `ChannelDeliverySettings` in
    production wiring and from per-test fixtures in tests. Keeping it out
    of module globals avoids tests stomping on each other and the
    config-vs-code drift that comes with hardcoded names.
    """

    def __init__(self, broker: BrokerClient, *, stream: str) -> None:
        self._broker = broker
        self._stream = stream

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
        return await self._broker.submit(self._stream, fields)


class ChannelDeliveryConsumer:
    """Worker loop: claim outbound entries, deliver via adapter, settle.

    On `RetryableError`: leave un-ACKed; broker redelivers after PEL idle
    timeout (paired with `StreamAutoclaimer` to recover dead consumers).
    On `FatalError` (or contract violations classified as fatal): ACK +
    DLQ-emit so the message doesn't loop forever.
    """

    def __init__(
        self,
        broker: BrokerClient,
        dedup: DedupCache,
        adapter_resolver,  # Callable[[str], ChannelAdapter | None]
        *,
        stream: str,
        group: str,
        dlq_stream: str,
        consumer_id: str = "c1",
        block_ms: int = 5000,
        batch_size: int = 10,
        max_delivery_attempts: int = 20,
    ) -> None:
        self._broker = broker
        self._dedup = dedup
        self._resolve_adapter = adapter_resolver
        self._stream = stream
        self._group = group
        self._dlq_stream = dlq_stream
        self._consumer_id = consumer_id
        self._block_ms = block_ms
        self._batch_size = batch_size
        self._max_delivery_attempts = max_delivery_attempts
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        await self._broker.ensure_group(self._stream, self._group, start="0")
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="channel-delivery-consumer")
        logger.info(
            "ChannelDeliveryConsumer started (stream=%s group=%s consumer=%s)",
            self._stream,
            self._group,
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
        logger.info("ChannelDeliveryConsumer stopped (stream=%s)", self._stream)

    async def _run_loop(self) -> None:
        backoff = 1.0
        while self._running:
            try:
                msgs = await self._broker.consume(
                    self._stream,
                    self._group,
                    self._consumer_id,
                    count=self._batch_size,
                    block_ms=self._block_ms,
                )
                for msg in msgs:
                    await self._handle(msg)
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
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

    async def _handle(self, msg: BrokerMessage) -> None:
        fields = msg.fields
        dedup_key = fields.get("dedup_key") or msg.id

        # Poison cap: if the broker has already redelivered this beyond
        # the configured ceiling, DLQ it regardless of why it kept
        # failing. Catches both transient outages outlasting the budget
        # and true poison (always-raising adapter code).
        if msg.delivery_count > self._max_delivery_attempts:
            await self._dead_letter(
                msg,
                f"max delivery attempts ({msg.delivery_count}) exceeded",
            )
            return

        # Dedup BEFORE the side effect — duplicates (broker redelivery,
        # autoclaim race) just ACK and return without re-sending.
        if not await self._dedup.claim(dedup_key):
            logger.debug("dedup hit on %s, acking", dedup_key)
            await self._broker.ack(self._stream, self._group, msg.id)
            return

        channel_type = fields.get("channel_type", "")
        try:
            channel_config = json.loads(fields.get("channel_config", "{}"))
        except json.JSONDecodeError as exc:
            # Malformed producer payload — true fatal, won't be fixed by retry.
            await self._dead_letter(msg, f"bad channel_config: {exc}")
            return

        message = fields.get("message", "")

        adapter = self._resolve_adapter(channel_type)
        if adapter is None:
            # Unknown channel_type is often transient: a partial rollout
            # where the adapter hasn't been registered yet, or a
            # config-driven extension not loaded. Release dedup and let
            # the broker redeliver; if it stays unresolvable, the
            # delivery_count cap above will DLQ it eventually.
            logger.warning(
                "no adapter for %r (dedup_key=%s, delivery_count=%d) — releasing for redelivery",
                channel_type,
                dedup_key,
                msg.delivery_count,
            )
            await self._dedup.release(dedup_key)
            return

        try:
            await adapter.send(channel_config, message)
        except RetryableError as exc:
            logger.warning(
                "delivery retryable %s/%s (attempt %d): %s",
                channel_type,
                dedup_key,
                msg.delivery_count,
                exc,
            )
            # CRITICAL: release the dedup claim so the broker's redelivery
            # (or XAUTOCLAIM hand-off to another consumer) can actually
            # attempt the send again. Without this, the next consumer hits
            # the still-set dedup key, ACKs, and the message vanishes.
            await self._dedup.release(dedup_key)
            return  # no ACK → broker redelivers via PEL idle
        except (FatalError, ChannelDeliveryError) as exc:
            await self._dead_letter(msg, f"{type(exc).__name__}: {exc}")
            return
        except Exception:
            # Unknown errors: same release-then-redeliver pattern. The
            # delivery_count cap (above) bounds the loop for true poison;
            # transient unknowns get a few free retries this way.
            logger.exception("delivery unexpected error on %s", dedup_key)
            await self._dedup.release(dedup_key)
            return

        await self._broker.ack(self._stream, self._group, msg.id)
        logger.debug("delivered %s/%s (attempt %d)", channel_type, dedup_key, msg.delivery_count)

    async def _dead_letter(self, msg: BrokerMessage, reason: str) -> None:
        dlq_fields = {**msg.fields, "fatal_reason": reason[:500]}
        try:
            await self._broker.submit(self._dlq_stream, dlq_fields)
        except Exception:
            logger.exception("failed to write to DLQ for %s", msg.id)
        await self._broker.ack(self._stream, self._group, msg.id)
        logger.error("channel delivery DLQ'd: %s (reason=%s)", msg.id, reason)
