"""The context store: recalling history and storing offloaded outputs and history."""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from agentarea_common.events.contract import EVENT_TYPES, LIVE_ONLY_TYPES
from agentarea_tasks.domain.feed import feed_event
from agentarea_tasks.infrastructure.task_log import TaskFeedReader
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

# What the task log keeps: every stored event type, and the messages people sent.
RECALLABLE_TYPES = EVENT_TYPES - LIVE_ONLY_TYPES


def make_context_activities(
    dependencies: ActivityDependencies, container: ActivityServiceContainer
) -> list[Callable[..., Any]]:
    from ..dependencies import ActivityContext, create_user_context

    @activity.defn
    async def recall_history_activity(
        request: RecallHistoryRequest,
    ) -> RecallHistoryResult:
        """Recall this task's history from its log: its events and the messages people sent.

        Lets an agent recover context compacted out of its working set, or review
        an earlier run of the task. Only the task's own log is read. A type
        outside the event vocabulary is refused with the list of valid ones.
        """
        unknown = [t for t in request.event_types or [] if t not in RECALLABLE_TYPES]
        if unknown:
            return RecallHistoryResult(
                summary=(
                    f"Unknown event types {unknown}. Event types are dotted, one of: "
                    + ", ".join(sorted(RECALLABLE_TYPES))
                )
            )
        user_context = create_user_context(request.user_context_data)
        try:
            async with ActivityContext(container, user_context) as ctx:
                session = container._database.async_session_factory()
                ctx._sessions.append(session)
                entries = await TaskFeedReader(session, user_context).latest_of_types(
                    request.task_id, request.event_types or [], limit=request.limit
                )
        except Exception as e:
            logger.error(f"Failed to recall history for task {request.task_id}: {e}", exc_info=True)
            return RecallHistoryResult(summary=f"Failed to recall history: {e}")

        events_data = []
        for entry in entries:
            shown = feed_event(entry)
            if shown is None:
                continue
            event_type, data = shown
            events_data.append(
                {
                    "event_type": event_type,
                    "data": data,
                    "created_at": str(entry.occurred_at or ""),
                }
            )
        counts: dict[str, int] = {}
        for event in events_data:
            counts[event["event_type"]] = counts.get(event["event_type"], 0) + 1
        summary_parts = [f"{count}x {etype}" for etype, count in counts.items()]
        return RecallHistoryResult(
            events=events_data,
            total_count=len(events_data),
            summary=f"Retrieved {len(events_data)} events: {', '.join(summary_parts)}",
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
