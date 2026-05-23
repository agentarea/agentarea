"""Redis pub/sub subscriber that feeds workflow events into ChannelRouter."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

import redis.asyncio as redis

if TYPE_CHECKING:
    from .router import ChannelRouter

logger = logging.getLogger(__name__)

# Workflow events are published to agentarea.events.workflow.* channels.
# We subscribe to the wildcard pattern so we receive all workflow events
# (WorkflowCompleted, WorkflowFailed, LLMCallChunk, etc.) without having to
# enumerate every type.
_WORKFLOW_CHANNEL_PATTERN = "agentarea.events.workflow.*"


class ChannelEventSubscriber:
    """Subscribes to Redis workflow event channels and dispatches to ChannelRouter.

    Uses redis.asyncio pubsub directly — EventBroker.subscribe() is not
    implemented and cannot be used here.

    Handles reconnection transparently: if the Redis connection drops the
    subscriber restarts with exponential back-off.
    """

    def __init__(self, router: ChannelRouter, redis_url: str) -> None:
        self._router = router
        self._redis_url = redis_url
        self._task: asyncio.Task[None] | None = None
        self._running = False

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background subscription task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="channel-event-subscriber")
        logger.info("ChannelEventSubscriber started (pattern=%s)", _WORKFLOW_CHANNEL_PATTERN)

    async def stop(self) -> None:
        """Stop the background subscription task gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("ChannelEventSubscriber stopped")

    # ── Internal loop ─────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """Outer loop: reconnects on Redis errors with exponential back-off."""
        backoff = 1.0
        while self._running:
            try:
                await self._subscribe_and_dispatch()
                backoff = 1.0  # reset after clean exit
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._running:
                    break
                logger.error(
                    "ChannelEventSubscriber Redis error (retrying in %.0fs): %s",
                    backoff,
                    exc,
                    exc_info=True,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _subscribe_and_dispatch(self) -> None:
        """Open a psubscribe connection and forward messages to the router."""
        # Use decode_responses=False to handle both raw Redis JSON and
        # FastStream binary messages on the same channel gracefully.
        client: redis.Redis = redis.from_url(self._redis_url, decode_responses=False)
        pubsub = client.pubsub()

        try:
            await pubsub.psubscribe(_WORKFLOW_CHANNEL_PATTERN)
            logger.debug("psubscribed to %s", _WORKFLOW_CHANNEL_PATTERN)

            async for raw_message in pubsub.listen():
                if not self._running:
                    break

                # pubsub.listen() yields subscription-confirmation messages
                # (type "psubscribe") as well as data messages (type "pmessage").
                msg_type = raw_message.get("type", b"")
                if msg_type not in ("pmessage", b"pmessage"):
                    continue

                await self._handle_message(raw_message)
        finally:
            try:
                await pubsub.punsubscribe(_WORKFLOW_CHANNEL_PATTERN)
                await pubsub.close()
            except Exception as exc:
                logger.debug("Pubsub cleanup error suppressed: %s", exc)
            try:
                await client.aclose()
            except Exception as exc:
                logger.debug("Redis client close error suppressed: %s", exc)

    async def _handle_message(self, raw_message: dict[str, Any]) -> None:
        """Parse a raw pubsub message and call router.on_task_event()."""
        try:
            raw_data = raw_message.get("data", b"")
            if not raw_data:
                return

            # Decode bytes to string; skip FastStream binary-framed messages
            if isinstance(raw_data, bytes):
                try:
                    payload = raw_data.decode("utf-8")
                except UnicodeDecodeError:
                    return  # FastStream binary message — skip
            else:
                payload = raw_data

            envelope: dict[str, Any] = json.loads(payload)

            # The envelope follows SharedEventFormat (CloudEvents-compatible):
            #   type        → e.g. "workflow.WorkflowCompleted"
            #   data        → original event data dict
            #   aggregate_id / data.task_id → task id
            raw_event_type: str = envelope.get("type", "")
            # Strip the "workflow." prefix to get the canonical event_type
            event_type = (
                raw_event_type[len("workflow.") :]
                if raw_event_type.startswith("workflow.")
                else raw_event_type
            )

            data: dict[str, Any] = envelope.get("data", {})
            # The actual event payload lives in original_data (set by publish activity).
            # Merge it into data so adapters see fields like "result" at top level.
            original_data = data.get("original_data")
            if isinstance(original_data, dict):
                data = {**data, **original_data}
            task_id = (
                data.get("task_id") or envelope.get("aggregate_id") or data.get("aggregate_id")
            )

            # event_id lives at the CloudEvents envelope root (key "id"),
            # not inside data. The router needs it to build a stable dedup
            # key so two distinct workflow events with the same type aren't
            # mistaken for redeliveries of each other.
            event: dict[str, Any] = {
                "event_type": event_type,
                "task_id": task_id,
                "event_id": envelope.get("id"),
                "data": data,
                # channel_origin may be embedded in data by the workflow
                "channel_origin": data.get("channel_origin"),
            }

            await self._router.on_task_event(event)

        except Exception:
            logger.exception("Failed to handle channel event message")
