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
from typing import Any
from uuid import UUID

from agentarea_common.broker.redis_streams import RedisStreamsBroker
from agentarea_common.config import get_settings
from agentarea_common.events.adapters.redis_streams import RedisStreamsEventStream
from agentarea_common.events.contract import LLM_CHUNK
from agentarea_common.events.task_stream import TaskEventEnvelope, iter_task_event_feed
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Rows per catch-up query. Each batch opens its own short session, so a slow
# client never holds a pooled connection while it drains the snapshot.
SNAPSHOT_BATCH_SIZE = 500

# Scoped to ``workspace_id`` as well as ``task_id``. Event payloads carry message
# content and tool arguments, so a query keyed on the task id alone reads across
# every tenant and depends entirely on the caller having checked ownership
# first — see ``TaskEventRepository.list_for_task``.
_TASK_EVENTS = (
    "SELECT id, event_type, timestamp, data FROM task_events "
    "WHERE task_id = :task_id AND workspace_id = :workspace_id"
)


def _envelope(row: Any) -> TaskEventEnvelope:
    return TaskEventEnvelope(
        event_type=row.event_type,
        event_id=str(row.id),
        timestamp=row.timestamp.isoformat(),
        data=dict(row.data or {}),
    )


async def _load_cursor(task_id: str, workspace_id: str, event_id: str) -> TaskEventEnvelope | None:
    """The stored event a reconnecting client last saw, if it is this task's."""
    from agentarea_api.api.deps.database import get_db_session

    try:
        event_uuid = UUID(event_id)
    except ValueError:
        return None
    async with get_db_session() as session:
        row = (
            await session.execute(
                text(f"{_TASK_EVENTS} AND id = :event_id"),
                {"task_id": task_id, "workspace_id": workspace_id, "event_id": event_uuid},
            )
        ).first()
    return _envelope(row) if row else None


async def _iter_snapshot(
    task_id: str,
    workspace_id: str,
    after: TaskEventEnvelope | None = None,
    *,
    batch_size: int = SNAPSHOT_BATCH_SIZE,
) -> AsyncIterator[TaskEventEnvelope]:
    """Task history from the durable event log in ``(timestamp, id)`` order.

    Read in keyset batches, starting after ``after`` when a client resumes.
    """
    from agentarea_api.api.deps.database import get_db_session

    position = (
        (datetime.fromisoformat(after.timestamp), UUID(after.event_id))
        if after is not None and after.timestamp
        else None
    )
    while True:
        params: dict[str, Any] = {
            "task_id": task_id,
            "workspace_id": workspace_id,
            "limit": batch_size,
        }
        query = _TASK_EVENTS
        if position is not None:
            query += (
                " AND (timestamp, id) > "
                "(CAST(:after_timestamp AS timestamptz), CAST(:after_id AS uuid))"
            )
            params["after_timestamp"], params["after_id"] = position
        query += " ORDER BY timestamp, id LIMIT :limit"
        async with get_db_session() as session:
            rows = (await session.execute(text(query), params)).fetchall()
        for row in rows:
            yield _envelope(row)
        if len(rows) < batch_size:
            return
        position = (rows[-1].timestamp, rows[-1].id)


# Incremental LLM chunk event type (canonical) dropped when a caller opts out
# of chunks.
CHUNK_EVENT_TYPES = frozenset({LLM_CHUNK})


async def open_task_event_feed(
    task_id: UUID | str,
    *,
    workspace_id: str,
    terminal_types: frozenset[str],
    exclude_types: frozenset[str] = frozenset(),
    include_chunks: bool = True,
    follow_execution: bool = False,
    last_event_id: str | None = None,
) -> AsyncIterator[TaskEventEnvelope]:
    """Yield a task's events (catch-up then live) and close the broker when done.

    ``workspace_id`` scopes the durable catch-up read; it is required so that a
    caller cannot open a feed without naming the tenant whose events it is
    entitled to, independently of the ownership check it already made.
    ``terminal_types`` ends the feed after a terminal event; ``exclude_types``
    drops event types the caller does not want. ``include_chunks`` defaults to
    True (high-volume ``llm.call.chunk`` events are surfaced); pass False to add
    the chunk types to ``exclude_types``. ``last_event_id`` (the SSE
    ``Last-Event-ID``) resumes after that stored event; an id this task does
    not have replays the whole history, which the client dedups by event id.
    """
    if not workspace_id:
        raise ValueError("workspace_id is required to open a task event feed")
    if not include_chunks:
        exclude_types = exclude_types | CHUNK_EVENT_TYPES
    tid = str(task_id)
    resume_after = None
    if last_event_id:
        resume_after = await _load_cursor(tid, workspace_id, last_event_id)
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
            snapshot=lambda: _iter_snapshot(tid, workspace_id, resume_after),
            terminal_types=terminal_types,
            exclude_types=exclude_types,
            follow_execution=follow_execution,
            resume_after=resume_after,
        ):
            yield env
    finally:
        await broker.aclose()
