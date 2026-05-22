"""Channel router: subscribes to task events, enqueues durable delivery jobs.

The router resolves channel_origin + formats the message, then submits the
job to the outbound Redis Stream via `ChannelDeliveryEmitter`. The actual
adapter call happens in `ChannelDeliveryConsumer` so transient failures
get retried by the broker instead of silently swallowed.
"""

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from agentarea_execution.workflows.visibility import PresentationMode, is_visible

from . import get_adapter
from .delivery_consumer import ChannelDeliveryEmitter

logger = logging.getLogger(__name__)

# Type for async task lookup: task_id → task_parameters dict
TaskLookup = Callable[[str], Coroutine[Any, Any, dict[str, Any] | None]]


class ChannelRouter:
    """Resolves channel context for workflow events and enqueues delivery.

    Routing decision (which channel, which formatting, visibility filter) is
    fast and stateless; the slow part — calling the remote adapter — runs in
    the delivery consumer. The router caches channel_origin per task_id to
    avoid repeated DB lookups.
    """

    def __init__(
        self,
        emitter: ChannelDeliveryEmitter,
        task_lookup: TaskLookup | None = None,
    ):
        self._emitter = emitter
        self._task_lookup = task_lookup
        self._origin_cache: dict[str, dict[str, Any] | None] = {}

    async def on_task_event(self, event: dict[str, Any]) -> None:
        """Handle a workflow event from the event pipeline."""
        channel_origin = event.get("channel_origin")
        if not channel_origin:
            task_id = event.get("task_id") or event.get("aggregate_id")
            if task_id:
                channel_origin = await self._resolve_channel_origin(str(task_id))

        if not channel_origin:
            return  # WebUI task — handled by existing SSE

        event_type = event.get("event_type", "")
        presentation = channel_origin.get("presentation", PresentationMode.CONCISE)

        if not is_visible(event_type, presentation):
            return

        channel_type = channel_origin.get("type")
        if not channel_type:
            logger.warning("channel_origin missing 'type': %s", channel_origin)
            return

        adapter = get_adapter(channel_type)
        if not adapter:
            logger.warning("No adapter registered for channel type: %s", channel_type)
            return

        message = adapter.format(event, presentation)

        # Dedup key: stable across broker redelivery and pub/sub re-fire.
        # We key on (task_id, event_type, event id) so the same workflow event
        # routed twice is the same delivery job.
        task_id = event.get("task_id") or event.get("aggregate_id") or ""
        event_id = event.get("data", {}).get("event_id") or ""
        dedup_key = f"{task_id}:{event_type}:{event_id}"

        await self._emitter.submit(
            channel_type=channel_type,
            channel_config=channel_origin,
            message=message,
            dedup_key=dedup_key,
        )

        if event_type in ("WorkflowCompleted", "WorkflowFailed", "WorkflowCancelled"):
            self._origin_cache.pop(str(task_id), None)

    async def _resolve_channel_origin(self, task_id: str) -> dict[str, Any] | None:
        if task_id in self._origin_cache:
            return self._origin_cache[task_id]

        if not self._task_lookup:
            self._origin_cache[task_id] = None
            return None

        try:
            task_params = await self._task_lookup(task_id)
            origin = (task_params or {}).get("channel_origin")
            self._origin_cache[task_id] = origin
            return origin
        except Exception:
            logger.exception("Failed to look up task %s for channel routing", task_id)
            self._origin_cache[task_id] = None
            return None

    def clear_cache(self, task_id: str | None = None) -> None:
        if task_id:
            self._origin_cache.pop(task_id, None)
        else:
            self._origin_cache.clear()
