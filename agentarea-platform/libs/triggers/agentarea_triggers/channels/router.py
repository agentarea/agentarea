"""Channel router: subscribes to task events, dispatches to outbound adapters."""

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from agentarea_execution.workflows.visibility import PresentationMode, is_visible

from . import ChannelAdapter, get_adapter

logger = logging.getLogger(__name__)

# Type for async task lookup: task_id → task_parameters dict
TaskLookup = Callable[[str], Coroutine[Any, Any, dict[str, Any] | None]]


class ChannelRouter:
    """Routes workflow events to external channel adapters.

    Sits between the event pipeline (Redis pub/sub) and outbound channel adapters.
    For each event, resolves the task's channel_origin (from event data or via
    task lookup) and dispatches to the appropriate adapter with presentation filtering.

    The router caches channel_origin per task_id to avoid repeated DB lookups.
    """

    def __init__(self, task_lookup: TaskLookup | None = None):
        """Initialize router.

        Args:
            task_lookup: Async callable that returns task_parameters for a task_id.
                         Used to resolve channel_origin when not in the event itself.
        """
        self._task_lookup = task_lookup
        self._origin_cache: dict[str, dict[str, Any] | None] = {}

    async def on_task_event(self, event: dict[str, Any]) -> None:
        """Handle a workflow event from the event pipeline.

        Args:
            event: Dict with keys: event_type, task_id, data, and optionally
                   channel_origin (injected from task_parameters).
        """
        # Try to get channel_origin from the event directly
        channel_origin = event.get("channel_origin")

        # If not on event, resolve from task lookup (with caching)
        if not channel_origin:
            task_id = event.get("task_id") or event.get("aggregate_id")
            if task_id:
                channel_origin = await self._resolve_channel_origin(str(task_id))

        if not channel_origin:
            return  # WebUI task — handled by existing SSE

        event_type = event.get("event_type", "")
        presentation = channel_origin.get("presentation", PresentationMode.CONCISE)

        # Check visibility filter
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

        await _dispatch(adapter, channel_origin, event, presentation)

    async def _resolve_channel_origin(self, task_id: str) -> dict[str, Any] | None:
        """Resolve channel_origin for a task, using cache."""
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
        """Clear cached channel_origin entries."""
        if task_id:
            self._origin_cache.pop(task_id, None)
        else:
            self._origin_cache.clear()


async def _dispatch(
    adapter: ChannelAdapter,
    channel_config: dict[str, Any],
    event: dict[str, Any],
    presentation: str,
) -> None:
    """Format and send an event through a channel adapter."""
    try:
        message = adapter.format(event, presentation)
        await adapter.send(channel_config, message)
        logger.debug(
            "Dispatched %s to %s",
            event.get("event_type"),
            channel_config.get("type"),
        )
    except Exception:
        logger.exception(
            "Failed to dispatch event %s to channel %s",
            event.get("event_type"),
            channel_config.get("type"),
        )
