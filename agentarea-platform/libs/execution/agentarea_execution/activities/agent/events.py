"""Publishing workflow events to the event store and live subscribers."""

import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.events.task_stream import publish_task_event
from temporalio import activity

from ...interfaces import ActivityDependencies
from ...models import WorkflowEventsRequest, WorkflowEventsResult

if TYPE_CHECKING:
    from ..dependencies import ActivityServiceContainer

logger = logging.getLogger(__name__)


async def load_task_parameters(
    container: "ActivityServiceContainer", user_context: UserContext, task_id: str
) -> dict[str, Any]:
    """The task's parameters, which carry its channel origin and A2A push configs."""
    from agentarea_tasks.infrastructure.repository import TaskRepository

    from ..dependencies import ActivityContext

    async with ActivityContext(container, user_context) as ctx:
        session = container._database.async_session_factory()
        ctx._sessions.append(session)
        task = await TaskRepository(session, user_context).get_task(UUID(task_id))
    return dict(task.parameters or {}) if task else {}


def make_events_activities(
    dependencies: ActivityDependencies, container: "ActivityServiceContainer"
) -> list[Callable[..., Any]]:
    from ..dependencies import ActivityContext

    @activity.defn
    async def publish_workflow_events_activity(
        request: WorkflowEventsRequest,
    ) -> WorkflowEventsResult:
        """Store each workflow event, then fan it out to live readers and channels.

        The ``task_events`` row is the source of truth and is committed first.
        Any failure raises so Temporal retries the whole batch; every step is
        safe to repeat because it is keyed by the workflow's ``event_id``: the
        row insert is a no-op for a stored id, the stream carries that id for the
        read side to dedup, and channel deliveries are deduplicated by a key
        built from it.
        """
        user_context = UserContext(user_id=request.user_id, workspace_id=request.workspace_id)
        task_parameters: dict[str, dict[str, Any]] = {}

        async def parameters_of(task_id: str) -> dict[str, Any]:
            if task_id not in task_parameters:
                task_parameters[task_id] = await load_task_parameters(
                    container, user_context, task_id
                )
            return task_parameters[task_id]

        try:
            events = [json.loads(event_json) for event_json in request.events_json]
            async with ActivityContext(container, user_context) as ctx:
                task_event_service = await ctx.get_task_event_service()
                stored_events = [
                    await task_event_service.create_workflow_event(
                        task_id=UUID(event["data"]["task_id"]),
                        event_id=UUID(event["event_id"]),
                        event_type=event["event_type"],
                        data=event["data"],
                        timestamp=datetime.fromisoformat(event["timestamp"]),
                        workspace_id=request.workspace_id,
                        created_by=request.user_id,
                    )
                    for event in events
                ]

            for event, stored in zip(events, stored_events, strict=True):
                if dependencies.broker_client is not None:
                    await publish_task_event(
                        dependencies.broker_client,
                        task_id=str(stored.task_id),
                        event_type=stored.event_type,
                        data=stored.data,
                        event_id=str(stored.id),
                        timestamp=stored.timestamp.isoformat(),
                    )

                if dependencies.broker_client and dependencies.channel_delivery_settings:
                    await _emit_channel_deliveries(
                        event,
                        str(stored.task_id),
                        parameters_of,
                        dependencies.broker_client,
                        dependencies.channel_delivery_settings.OUTBOUND_STREAM,
                    )
        except Exception:
            logger.error(
                "Failed to publish %d workflow events for workspace %s",
                len(request.events_json),
                request.workspace_id,
                exc_info=True,
            )
            raise

        return WorkflowEventsResult(success=True, events_published=len(request.events_json))

    return [
        publish_workflow_events_activity,
    ]


async def _emit_channel_deliveries(
    event: dict[str, Any],
    task_id: str,
    parameters_of: Callable[[str], Any],
    broker: Any,
    stream: str,
) -> None:
    from agentarea_triggers.channels.activity_emit import emit_channel_delivery

    data = event["data"]
    channel_origin = data.get("channel_origin")
    if not channel_origin:
        channel_origin = (await parameters_of(task_id)).get("channel_origin")

    event_with_id = {
        "event_type": event["event_type"],
        "event_id": event["event_id"],
        "task_id": task_id,
        "data": data,
    }
    await emit_channel_delivery(
        event=event_with_id,
        channel_origin=channel_origin,
        broker=broker,
        stream=stream,
    )

    push_configs = (await parameters_of(task_id)).get("a2a_push_configs")
    for cfg in push_configs if isinstance(push_configs, list) else []:
        cfg_id = cfg.get("id")
        cfg_url = cfg.get("url")
        if not cfg_id or not cfg_url:
            continue
        await emit_channel_delivery(
            event=event_with_id,
            channel_origin={
                "type": "a2a_webhook",
                "url": cfg_url,
                "task_id": task_id,
                "config_id": cfg_id,
                "presentation": "silent",
            },
            broker=broker,
            stream=stream,
            dedup_suffix=f"a2a:{cfg_id}",
        )
