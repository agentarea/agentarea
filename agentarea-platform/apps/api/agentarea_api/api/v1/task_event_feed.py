"""Shared task-event read side for SSE and A2A streaming (ADR-0018).

Both the frontend SSE and the A2A endpoint serve a task's event feed. This is a
CQRS catch-up subscription, not a poll of the write model: replay the full
history from the durable ``task_events`` table (catch-up), then live-tail the
per-task Redis stream the worker XADDs to. Dedup by event id makes the hand-off
race-free. See ``agentarea_common.events.task_stream``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from agentarea_common.broker.redis_streams import RedisStreamsBroker
from agentarea_common.config import get_settings
from agentarea_common.events.adapters.redis_streams import RedisStreamsEventStream
from agentarea_common.events.contract import LLM_CHUNK
from agentarea_common.events.task_stream import TaskEventEnvelope, iter_task_event_feed
from sqlalchemy import text


async def _load_snapshot(task_id: str) -> list[TaskEventEnvelope]:
    """Full task history from the durable event log, in order (catch-up)."""
    from agentarea_api.api.deps.database import get_db_session

    async with get_db_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, event_type, timestamp, data "
                    "FROM task_events "
                    "WHERE task_id = :task_id "
                    "ORDER BY timestamp ASC"
                ),
                {"task_id": task_id},
            )
        ).fetchall()
    return [
        TaskEventEnvelope(
            event_type=row.event_type,
            event_id=str(row.id),
            timestamp=row.timestamp.isoformat() if row.timestamp else None,
            data=dict(row.data or {}),
        )
        for row in rows
    ]


# Incremental LLM chunk event type (canonical) dropped when a caller opts out
# of chunks.
CHUNK_EVENT_TYPES = frozenset({LLM_CHUNK})


async def open_task_event_feed(
    task_id: UUID | str,
    *,
    terminal_types: frozenset[str],
    exclude_types: frozenset[str] = frozenset(),
    include_chunks: bool = True,
) -> AsyncIterator[TaskEventEnvelope]:
    """Yield a task's events (catch-up then live) and close the broker when done.

    ``terminal_types`` ends the feed after a terminal event; ``exclude_types``
    drops event types the caller does not want. ``include_chunks`` defaults to
    True (high-volume ``llm.call.chunk`` events are surfaced); pass False to add
    the chunk types to ``exclude_types``.
    """
    if not include_chunks:
        exclude_types = exclude_types | CHUNK_EVENT_TYPES
    tid = str(task_id)
    redis_url = getattr(get_settings().broker, "REDIS_URL", "redis://localhost:6379")
    broker = RedisStreamsBroker(redis_url)
    stream = RedisStreamsEventStream(broker)
    try:
        async for env in iter_task_event_feed(
            stream=stream,
            task_id=tid,
            snapshot=lambda: _load_snapshot(tid),
            terminal_types=terminal_types,
            exclude_types=exclude_types,
        ):
            yield env
    finally:
        await broker.aclose()
