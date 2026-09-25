"""The context store: recalling history and storing offloaded outputs and history."""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from temporalio import activity

from ...interfaces import ActivityDependencies
from ...models import (
    ReadOutputRequest,
    ReadOutputResult,
    RecallHistoryRequest,
    RecallHistoryResult,
    SearchHistoryRequest,
    SearchHistoryResult,
    StoreHistoryRequest,
    StoreHistoryResult,
    StoreOutputRequest,
    StoreOutputResult,
)

if TYPE_CHECKING:
    from ..dependencies import ActivityServiceContainer

logger = logging.getLogger(__name__)


def make_context_activities(
    dependencies: ActivityDependencies, container: "ActivityServiceContainer"
) -> list[Callable[..., Any]]:
    from ..dependencies import ActivityContext, create_user_context

    @activity.defn
    async def recall_history_activity(
        request: RecallHistoryRequest,
    ) -> RecallHistoryResult:
        """Recall context from past task executions via the DB event log (tier 2).

        Allows agents to recover context that was compacted out of the
        working set, or to review what happened in earlier executions.
        """
        user_context = create_user_context(request.user_context_data)
        async with ActivityContext(container, user_context) as ctx:
            task_event_service = await ctx.get_task_event_service()

            try:
                # Fetch events, optionally filtered by type
                if request.event_types:
                    events = []
                    for event_type in request.event_types:
                        type_events = await task_event_service.get_events_by_type(
                            event_type=event_type,
                            limit=request.limit,
                        )
                        events.extend(type_events)
                    # Sort by timestamp descending, limit total
                    events.sort(
                        key=lambda e: e.created_at if hasattr(e, "created_at") else "",
                        reverse=True,
                    )
                    events = events[: request.limit]
                else:
                    events = await task_event_service.get_task_events(
                        task_id=request.task_id,
                        limit=request.limit,
                    )

                # Serialize events to dicts
                events_data = []
                for event in events:
                    event_dict = {
                        "event_type": event.event_type,
                        "data": event.data if hasattr(event, "data") else {},
                        "created_at": str(event.timestamp) if hasattr(event, "timestamp") else "",
                    }
                    events_data.append(event_dict)

                # Build a brief summary
                event_type_counts: dict[str, int] = {}
                for e in events_data:
                    t = e.get("event_type", "unknown")
                    event_type_counts[t] = event_type_counts.get(t, 0) + 1

                summary_parts = [f"{count}x {etype}" for etype, count in event_type_counts.items()]
                summary = f"Retrieved {len(events_data)} events: {', '.join(summary_parts)}"

                return RecallHistoryResult(
                    events=events_data,
                    total_count=len(events_data),
                    summary=summary,
                )

            except Exception as e:
                logger.error(
                    f"Failed to recall history for task {request.task_id}: {e}", exc_info=True
                )
                return RecallHistoryResult(
                    summary=f"Failed to recall history: {e}",
                )

    @activity.defn(name="store_context_output")
    async def store_context_output_activity(request: StoreOutputRequest) -> StoreOutputResult:
        """Store a large tool output in MinIO for later retrieval."""
        from ...workflows.context_store import ContextStore

        context_store = ContextStore(workspace_id=request.workspace_id, task_id=request.task_id)
        try:
            await context_store.store_output(request.output_id, request.content)
            return StoreOutputResult(success=True)
        except Exception as e:
            logger.error(f"Failed to store context output {request.output_id}: {e}", exc_info=True)
            return StoreOutputResult(success=False, error=str(e))

    @activity.defn(name="read_context_output")
    async def read_context_output_activity(request: ReadOutputRequest) -> ReadOutputResult:
        """Read a stored tool output from MinIO with optional filtering."""
        from ...workflows.context_store import ContextStore

        context_store = ContextStore(workspace_id=request.workspace_id, task_id=request.task_id)
        try:
            content = await context_store.read_output(
                request.output_id, grep=request.grep, head=request.head, tail=request.tail
            )
            return ReadOutputResult(success=True, content=content)
        except Exception as e:
            logger.error(f"Failed to read context output {request.output_id}: {e}", exc_info=True)
            return ReadOutputResult(success=False, error=str(e))

    @activity.defn(name="store_history_chunk")
    async def store_history_chunk_activity(request: StoreHistoryRequest) -> StoreHistoryResult:
        """Store compacted messages in MinIO before they are summarized."""
        from ...workflows.context_store import ContextStore

        context_store = ContextStore(workspace_id=request.workspace_id, task_id=request.task_id)
        try:
            await context_store.store_history_chunk(request.chunk_index, request.messages)
            return StoreHistoryResult(success=True)
        except Exception as e:
            logger.error(f"Failed to store history chunk {request.chunk_index}: {e}", exc_info=True)
            return StoreHistoryResult(success=False, error=str(e))

    @activity.defn(name="search_history")
    async def search_history_activity(request: SearchHistoryRequest) -> SearchHistoryResult:
        """Search stored history chunks in MinIO."""
        from ...workflows.context_store import ContextStore

        context_store = ContextStore(workspace_id=request.workspace_id, task_id=request.task_id)
        try:
            results = await context_store.search_history(
                grep=request.grep, tool_name=request.tool_name
            )
            return SearchHistoryResult(success=True, results=results)
        except Exception as e:
            logger.error(f"Failed to search history: {e}", exc_info=True)
            return SearchHistoryResult(success=False, error=str(e))

    return [
        recall_history_activity,
        store_context_output_activity,
        read_context_output_activity,
        store_history_chunk_activity,
        search_history_activity,
    ]
