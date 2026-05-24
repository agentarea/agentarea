"""In-process channel-delivery dispatcher for Temporal activity callers.

Workflow events emitted by `publish_workflow_events_activity` need to
reach the outbound delivery stream durably. The old path went via Redis
pub/sub → `ChannelEventSubscriber` → router → emitter, which had a
lossy gap any time the subscriber wasn't running or crashed mid-handler.

This module runs the same routing logic — visibility filter, channel
resolution, adapter format, dedup_key construction, broker submit —
directly inside the Temporal activity. Activity-level at-least-once
retry now covers the previously-lossy hop, with no pub/sub bridge in
the delivery path.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from agentarea_execution.workflows.visibility import PresentationMode, is_visible

from . import get_adapter

if TYPE_CHECKING:
    from agentarea_common.broker import BrokerClient

logger = logging.getLogger(__name__)


async def emit_channel_delivery(
    *,
    event: dict[str, Any],
    channel_origin: dict[str, Any] | None,
    broker: BrokerClient,
    stream: str,
) -> bool:
    """Run the channel-routing decision and submit to the outbound stream.

    Returns True if the message was submitted, False if the event was
    skipped (no channel_origin, not visible, no adapter, missing
    event_id, etc.). Never raises — failures log and return False so
    the surrounding activity isn't poisoned by an unrelated event.
    """
    try:
        if not channel_origin:
            return False

        event_type = event.get("event_type", "")
        presentation = channel_origin.get("presentation", PresentationMode.CONCISE)

        if not is_visible(event_type, presentation):
            return False

        channel_type = channel_origin.get("type")
        if not channel_type:
            logger.warning("channel_origin missing 'type': %s", channel_origin)
            return False

        adapter = get_adapter(channel_type)
        if adapter is None:
            # Unknown channel: skip here rather than enqueue.
            # If the adapter ships later, future events for the same
            # task will start flowing. (The consumer's retry+cap path
            # only helps for messages already on the stream.)
            logger.warning("No adapter registered for channel type: %s", channel_type)
            return False

        message = adapter.format(event, presentation)

        task_id = event.get("task_id") or event.get("aggregate_id") or ""
        event_id = event.get("event_id") or ""
        if not event_id:
            logger.warning(
                "channel emit: missing event_id for task=%s event_type=%s — "
                "dedup will collapse repeats of this event into one delivery",
                task_id,
                event_type,
            )
        dedup_key = f"{task_id}:{event_type}:{event_id}"

        await broker.submit(
            stream,
            {
                "channel_type": channel_type,
                "channel_config": json.dumps(channel_origin),
                "message": message,
                "dedup_key": dedup_key,
            },
        )
        return True
    except Exception:  # noqa: BLE001
        # Channel emit failures must not break the whole activity batch.
        logger.exception("channel emit failed for event %s", event.get("event_type"))
        return False
