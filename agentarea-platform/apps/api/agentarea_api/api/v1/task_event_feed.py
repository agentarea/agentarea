"""Shared task-event read side for SSE and A2A streaming (ADR-0018).

Both the frontend SSE and the A2A endpoint serve a task's event feed. This is a
CQRS catch-up subscription, not a poll of the write model: replay the history
from the durable ``task_events`` table (catch-up), then live-tail the per-task
Redis stream the worker XADDs to. Dedup by event id makes the hand-off
race-free. A reconnect that names the last event it saw resumes after it. See
``agentarea_common.events.task_stream``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import datetime
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.broker.redis_streams import RedisStreamsBroker
from agentarea_common.config import get_settings
from agentarea_common.events.adapters.redis_streams import RedisStreamsEventStream
from agentarea_common.events.contract import LLM_CHUNK
from agentarea_common.events.task_stream import TaskEventEnvelope, iter_task_event_feed
from agentarea_tasks.domain.models import TaskEvent
from agentarea_tasks.infrastructure.repository import TaskEventRepository

logger = logging.getLogger(__name__)

# Rows per catch-up query. Each batch opens its own short session, so a slow
# client never holds a pooled connection while it drains the snapshot.
SNAPSHOT_BATCH_SIZE = 500


def _envelope(event: TaskEvent) -> TaskEventEnvelope:
    return TaskEventEnvelope(
        event_type=event.event_type,
        event_id=str(event.id),
        timestamp=event.timestamp.isoformat(),
        data=dict(event.data or {}),
    )


async def _load_cursor(
    task_id: str, user_context: UserContext, event_id: str
) -> TaskEventEnvelope | None:
    """The stored event a reconnecting client last saw, if it is this task's."""
    from agentarea_api.api.deps.database import get_db_session

    try:
        event_uuid = UUID(event_id)
    except ValueError:
        return None
    async with get_db_session() as session:
        event = await TaskEventRepository(session, user_context).get_task_event(
            UUID(task_id), event_uuid
        )
    return _envelope(event) if event else None


async def _iter_snapshot(
    task_id: str,
    user_context: UserContext,
    after: TaskEventEnvelope | None = None,
    *,
    batch_size: int = SNAPSHOT_BATCH_SIZE,
) -> AsyncIterator[TaskEventEnvelope]:
    """Task history from the durable event log in ``(timestamp, id)`` order.

    Read in keyset batches through the workspace-scoped repository, starting
    after ``after`` when a client resumes.
    """
    from agentarea_api.api.deps.database import get_db_session

    position = (
        (datetime.fromisoformat(after.timestamp), UUID(after.event_id))
        if after is not None and after.timestamp
        else None
    )
    while True:
        async with get_db_session() as session:
            events = await TaskEventRepository(session, user_context).page_for_task(
                UUID(task_id), after=position, limit=batch_size
            )
        for event in events:
            yield _envelope(event)
        if len(events) < batch_size:
            return
        position = (events[-1].timestamp, events[-1].id)


# Incremental LLM chunk event type (canonical) dropped when a caller opts out
# of chunks.
CHUNK_EVENT_TYPES = frozenset({LLM_CHUNK})


async def open_task_event_feed(
    task_id: UUID | str,
    *,
    user_context: UserContext,
    terminal_types: frozenset[str],
    exclude_types: frozenset[str] = frozenset(),
    include_chunks: bool = True,
    follow_execution: bool = False,
    last_event_id: str | None = None,
) -> AsyncIterator[TaskEventEnvelope]:
    """Yield a task's events (catch-up then live) and close the broker when done.

    ``user_context`` scopes the durable catch-up read to its workspace; it is
    required so that a caller cannot open a feed without naming the tenant whose
    events it is entitled to, independently of the ownership check it made.
    ``terminal_types`` ends the feed after a terminal event; ``exclude_types``
    drops event types the caller does not want. ``include_chunks`` defaults to
    True (high-volume ``llm.call.chunk`` events are surfaced); pass False to add
    the chunk types to ``exclude_types``. ``last_event_id`` (the SSE
    ``Last-Event-ID``) resumes after that stored event; an id this task does
    not have replays the whole history, which the client dedups by event id.
    """
    if not include_chunks:
        exclude_types = exclude_types | CHUNK_EVENT_TYPES
    tid = str(task_id)
    resume_after = None
    if last_event_id:
        resume_after = await _load_cursor(tid, user_context, last_event_id)
        if resume_after is None:
            logger.warning(
                "Last-Event-ID %s is not an event of task %s; replaying its history",
                last_event_id,
                tid,
            )
    redis_url = getattr(get_settings().broker, "REDIS_URL", "redis://localhost:6379")
    broker = RedisStreamsBroker(redis_url)
    stream = RedisStreamsEventStream(broker)
    try:
        async for env in iter_task_event_feed(
            stream=stream,
            task_id=tid,
            snapshot=lambda: _iter_snapshot(tid, user_context, resume_after),
            terminal_types=terminal_types,
            exclude_types=exclude_types,
            follow_execution=follow_execution,
            resume_after=resume_after,
        ):
            yield env
    finally:
        await broker.aclose()
