"""Publishing workflow events to the event store and live subscribers."""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.events.contract import LLM_FAILED, canonical_type
from temporalio import activity

from ...interfaces import ActivityDependencies
from ...models import WorkflowEventsRequest, WorkflowEventsResult

if TYPE_CHECKING:
    from ..dependencies import ActivityServiceContainer

logger = logging.getLogger(__name__)


def make_events_activities(
    dependencies: ActivityDependencies, container: "ActivityServiceContainer"
) -> list[Callable[..., Any]]:
    from ..dependencies import ActivityContext

    @activity.defn
    async def publish_workflow_events_activity(
        request: WorkflowEventsRequest,
    ) -> WorkflowEventsResult:
        """Publish workflow events."""
        try:
            import json
            from datetime import datetime
            from uuid import uuid4

            from agentarea_common.events.base_events import DomainEvent
            from agentarea_common.events.task_stream import publish_task_event

            from ...handlers import handle_llm_error_event
            from ..event_publisher import resolve_event_broker

            logger.info(f"Publishing {len(request.events_json)} workflow events via EventBroker")

            event_publisher = resolve_event_broker(dependencies.event_broker)
            events_published = 0
            errors = []

            # Per-invocation cache of task_parameters → channel_origin, used
            # to avoid N+1 lookups when a single batch carries multiple
            # events for the same task.
            channel_origin_cache: dict[str, dict | None] = {}
            push_configs_cache: dict[str, list] = {}

            async def _resolve_push_configs(task_id_str: str) -> list:
                if task_id_str in push_configs_cache:
                    return push_configs_cache[task_id_str]
                configs: list = []
                try:
                    from uuid import UUID as _UUID

                    from agentarea_tasks.infrastructure.repository import (
                        TaskRepository as _TaskRepository,
                    )

                    user_context_inner = UserContext(
                        user_id=request.user_id,
                        workspace_id=request.workspace_id,
                    )
                    async with ActivityContext(container, user_context_inner) as ctx_inner:
                        session_inner = container._database.async_session_factory()
                        ctx_inner._sessions.append(session_inner)
                        task_repo = _TaskRepository(session_inner, user_context_inner)
                        task = await task_repo.get_task(_UUID(task_id_str))
                        if task and task.parameters:
                            raw = task.parameters.get("a2a_push_configs")
                            if isinstance(raw, list):
                                configs = raw
                except Exception:
                    logger.exception("a2a push-config lookup failed for task=%s", task_id_str)
                push_configs_cache[task_id_str] = configs
                return configs

            async def _resolve_channel_origin(task_id_str: str) -> dict | None:
                if task_id_str in channel_origin_cache:
                    return channel_origin_cache[task_id_str]
                origin: dict | None = None
                try:
                    from uuid import UUID as _UUID

                    from agentarea_tasks.infrastructure.repository import (
                        TaskRepository as _TaskRepository,
                    )

                    user_context_inner = UserContext(
                        user_id=request.user_id,
                        workspace_id=request.workspace_id,
                    )
                    async with ActivityContext(container, user_context_inner) as ctx_inner:
                        session_inner = container._database.async_session_factory()
                        ctx_inner._sessions.append(session_inner)
                        task_repo = _TaskRepository(session_inner, user_context_inner)
                        task = await task_repo.get_task(_UUID(task_id_str))
                        if task and task.parameters:
                            origin = task.parameters.get("channel_origin")
                except Exception:
                    logger.exception("channel_origin lookup failed for task=%s", task_id_str)
                channel_origin_cache[task_id_str] = origin
                return origin

            for event_json in request.events_json:
                try:
                    event = json.loads(event_json)
                    task_id = event.get("data", {}).get("task_id", "unknown")

                    # Create proper domain event with correct parameters
                    domain_event = DomainEvent(
                        event_id=event.get("event_id", str(uuid4())),
                        event_type=f"workflow.{event['event_type']}",  # Prefix for workflow events
                        timestamp=datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")),
                        # All other data goes into the data dict
                        aggregate_id=task_id,
                        aggregate_type="task",
                        original_event_type=event["event_type"],
                        original_timestamp=event["timestamp"],
                        original_data=event[
                            "data"
                        ],  # Include the original event data for tool calls
                    )

                    # 1. Publish via RedisEventBroker (uses FastStream
                    # infrastructure) for real-time SSE
                    await event_publisher.publish(domain_event)
                    logger.debug(
                        f"Published workflow event: {event['event_type']} for task {task_id}"
                    )

                    # 2. Store event in database using proper service layer
                    try:
                        # Use workspace_id and user_id from workflow request (already present)
                        workspace_id = request.workspace_id
                        user_id = request.user_id

                        # Create proper user context with values from workflow
                        user_context = UserContext(
                            user_id=user_id,
                            workspace_id=workspace_id,
                        )

                        persisted_event = None
                        async with ActivityContext(container, user_context) as ctx:
                            task_event_service = await ctx.get_task_event_service()

                            # Create event using service - workspace_id and created_by are provided
                            persisted_event = await task_event_service.create_workflow_event(
                                task_id=UUID(task_id),
                                event_type=event["event_type"],
                                data=event["data"],
                                workspace_id=workspace_id,
                                created_by=user_id,
                            )

                            # Commit is handled by the service
                            logger.debug(
                                f"Stored event using service: {event['event_type']} for task {task_id}"
                            )

                        # Publish to the per-task live stream AFTER the DB commit,
                        # using the persisted row id so the read-side dedups the
                        # snapshot(DB) vs live(stream) overlap (ADR-0018). Durable
                        # history stays in task_events; this is the live tail.
                        if persisted_event is not None and dependencies.broker_client is not None:
                            await publish_task_event(
                                dependencies.broker_client,
                                task_id=str(persisted_event.task_id),
                                event_type=persisted_event.event_type,
                                data=persisted_event.data,
                                event_id=str(persisted_event.id),
                                timestamp=persisted_event.timestamp.isoformat()
                                if persisted_event.timestamp
                                else None,
                            )

                    except Exception as db_error:
                        logger.error(
                            f"Failed to store event using service: {db_error}", exc_info=True
                        )
                        errors.append(f"DB storage failed for {event['event_type']}: {db_error!s}")

                    # 3. Handle LLM error events locally for immediate action
                    if canonical_type(event["event_type"]) == LLM_FAILED:
                        try:
                            await handle_llm_error_event(domain_event)
                        except Exception as handler_error:
                            logger.error(
                                f"Failed to handle LLM error event: {handler_error}", exc_info=True
                            )
                            errors.append(f"Error handler failed: {handler_error!s}")

                    # 4. Durable outbound channel delivery: enqueue directly
                    # to the broker stream. Bypasses the lossy pub/sub bridge
                    # between workflow events and the delivery consumer.
                    # Temporal activity-level retry covers the previously
                    # silent failure window (worker crash between event
                    # receipt and stream submit).
                    if dependencies.broker_client and dependencies.channel_delivery_settings:
                        from agentarea_triggers.channels.activity_emit import emit_channel_delivery

                        # channel_origin source priority:
                        #   1. embedded in event.data (workflow has it inline)
                        #   2. task.parameters via DB lookup (cached per batch)
                        event_data = (
                            event.get("data") if isinstance(event.get("data"), dict) else {}
                        )
                        channel_origin = event_data.get("channel_origin") if event_data else None
                        if not channel_origin and task_id and task_id != "unknown":
                            channel_origin = await _resolve_channel_origin(str(task_id))

                        event_with_id = {
                            "event_type": event["event_type"],
                            "event_id": event.get("event_id"),
                            "task_id": task_id,
                            "data": event["data"],
                        }
                        await emit_channel_delivery(
                            event=event_with_id,
                            channel_origin=channel_origin,
                            broker=dependencies.broker_client,
                            stream=dependencies.channel_delivery_settings.OUTBOUND_STREAM,
                        )

                        # A2A push notifications: one delivery per registered webhook.
                        if task_id and task_id != "unknown":
                            for cfg in await _resolve_push_configs(str(task_id)):
                                cfg_id = cfg.get("id")
                                cfg_url = cfg.get("url")
                                if not cfg_id or not cfg_url:
                                    continue
                                await emit_channel_delivery(
                                    event=event_with_id,
                                    channel_origin={
                                        "type": "a2a_webhook",
                                        "url": cfg_url,
                                        "task_id": str(task_id),
                                        "config_id": cfg_id,
                                        "presentation": "silent",
                                    },
                                    broker=dependencies.broker_client,
                                    stream=dependencies.channel_delivery_settings.OUTBOUND_STREAM,
                                    dedup_suffix=f"a2a:{cfg_id}",
                                )

                    events_published += 1

                except Exception as event_error:
                    logger.error(f"Failed to process single event: {event_error}", exc_info=True)
                    errors.append(f"Event processing failed: {event_error!s}")

            return WorkflowEventsResult(
                success=len(errors) == 0,
                events_published=events_published,
                errors=errors,
            )

        except Exception as e:
            logger.error(f"Failed to publish workflow events: {e}", exc_info=True)
            return WorkflowEventsResult(
                success=False,
                events_published=0,
                errors=[f"Critical failure: {e!s}"],
            )

    return [
        publish_workflow_events_activity,
    ]
