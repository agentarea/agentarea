"""Channel router: subscribes to task events, dispatches to outbound adapters."""

import logging
from typing import Any

from agentarea_execution.workflows.visibility import PresentationMode, is_visible

from . import ChannelAdapter, get_adapter

logger = logging.getLogger(__name__)


class ChannelRouter:
    """Routes workflow events to external channel adapters.

    Sits between the event pipeline (Redis pub/sub) and outbound channel adapters.
    For each event, checks if the originating task has a channel_origin and
    dispatches to the appropriate adapter with presentation filtering.
    """

    async def on_task_event(self, event: dict[str, Any]) -> None:
        """Handle a workflow event from the event pipeline.

        Args:
            event: Dict with keys: event_type, task_id, data, and optionally
                   channel_origin (injected by the event pipeline from task_parameters).
        """
        channel_origin = event.get("channel_origin")
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
