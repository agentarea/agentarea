"""A task's event feed for SSE, A2A and the CLI (ADR-0043 §8, ADR-0042 §7).

The history is the task log: its event rows and the messages a person sent,
read from a ``seq``. New entries come from this process's one tail of
``tasks.events`` and its pub/sub connection for live-only signals
(``TaskEventsHub``). A reconnect that names the last ``seq`` it saw resumes
after it. See ``agentarea_common.events.task_stream``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.broker.redis_streams import RedisStreamsBroker
from agentarea_common.config import RedisSettings, get_settings
from agentarea_common.events.contract import LLM_CHUNK
from agentarea_common.events.task_stream import (
    TaskEventEnvelope,
    TaskEventsHub,
    iter_task_event_feed,
)
from agentarea_common.utils.types import utc_isoformat
from agentarea_tasks.domain.feed import FeedBodies, feed_event
from agentarea_tasks.domain.models import ConversationEntry
from agentarea_tasks.domain.statuses import ENDED_TASK_STATUSES
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.infrastructure.task_log import TaskFeedReader

logger = logging.getLogger(__name__)

# Rows per catch-up query. Each batch opens its own short session, so a slow
# client never holds a pooled connection while it drains the snapshot.
SNAPSHOT_BATCH_SIZE = 500

_hub: TaskEventsHub | None = None


def task_events_hub() -> TaskEventsHub:
    """The process's one tail of ``tasks.events``, shared by every open feed."""
    global _hub
    if _hub is None:
        settings = get_settings()
        if not isinstance(settings.broker, RedisSettings):
            raise RuntimeError(
                "The task feed reads the Redis broker; set AGENTAREA_BROKER=redis "
                + f"(current: {settings.broker.BROKER})"
            )
        _hub = TaskEventsHub(
            RedisStreamsBroker(settings.broker.REDIS_URL, namespace=settings.streams.NAMESPACE)
        )
    return _hub


async def close_task_events_hub() -> None:
    global _hub
    if _hub is not None:
        await _hub.aclose()
        _hub = None


def feed_envelope(
    entry: ConversationEntry, bodies: FeedBodies | None = None
) -> TaskEventEnvelope | None:
    """A log row as a feed entry, or None for a row the feed leaves out."""
    shown = feed_event(entry, bodies)
    if shown is None:
        return None
    event_type, data = shown
    return TaskEventEnvelope(
        event_type=event_type,
        event_id=str(entry.event_id),
        timestamp=utc_isoformat(entry.occurred_at) if entry.occurred_at else None,
        data=data,
        seq=entry.seq,
    )


async def _load_cursor(
    task_id: str, user_context: UserContext, last_event_id: str
) -> TaskEventEnvelope | None:
    """The feed entry at the ``seq`` a reconnecting client last saw, if this task has one."""
    from agentarea_api.api.deps.database import get_db_session

    try:
        seq = int(last_event_id)
    except ValueError:
        return None
    async with get_db_session() as session:
        entry = await TaskFeedReader(session, user_context).at(UUID(task_id), seq)
    return feed_envelope(entry) if entry is not None else None


async def _run_open(task_id: str, user_context: UserContext) -> bool:
    """Whether the task has a run that has not ended: a follow-up or a retry started one."""
    from agentarea_api.api.deps.database import get_db_session

    async with get_db_session() as session:
        task = await TaskRepository(session, user_context).get_task(UUID(task_id))
    return task is not None and task.status not in ENDED_TASK_STATUSES


async def _iter_snapshot(
    task_id: str,
    user_context: UserContext,
    after: TaskEventEnvelope | None = None,
    *,
    batch_size: int = SNAPSHOT_BATCH_SIZE,
) -> AsyncIterator[TaskEventEnvelope]:
    """The task's feed rows from the log in ``seq`` order, after ``after`` when a client resumes."""
    from agentarea_api.api.deps.database import get_db_session

    position = after.seq if after is not None and after.seq is not None else -1
    while True:
        async with get_db_session() as session:
            reader = TaskFeedReader(session, user_context)
            entries = await reader.after(UUID(task_id), after_seq=position, limit=batch_size)
            bodies = await reader.bodies(UUID(task_id), entries)
        for entry in entries:
            envelope = feed_envelope(entry, bodies)
            if envelope is not None:
                yield envelope
        if len(entries) < batch_size:
            return
        position = entries[-1].seq


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
    """Yield a task's feed: its log, then live entries.

    ``user_context`` scopes the log read to its workspace; it is required so
    that a caller cannot open a feed without naming the tenant whose events it
    is entitled to, independently of the ownership check it made.
    ``terminal_types`` ends the feed after a terminal event; ``exclude_types``
    drops event types the caller does not want. ``include_chunks`` defaults to
    True (high-volume ``llm.call.chunk`` signals are surfaced); pass False to
    add the chunk types to ``exclude_types``. ``last_event_id`` (the SSE
    ``Last-Event-ID``) is the ``seq`` of the last entry the client has; one
    this task's feed does not have replays the whole history, which the client
    dedups by event id.
    """
    if not include_chunks:
        exclude_types = exclude_types | CHUNK_EVENT_TYPES
    tid = str(task_id)
    resume_after = None
    if last_event_id:
        resume_after = await _load_cursor(tid, user_context, last_event_id)
        if resume_after is None:
            logger.warning(
                "Last-Event-ID %s is not a feed position of task %s; replaying its history",
                last_event_id,
                tid,
            )
    async for env in iter_task_event_feed(
        hub=task_events_hub(),
        task_id=tid,
        snapshot=lambda: _iter_snapshot(tid, user_context, resume_after),
        terminal_types=terminal_types,
        exclude_types=exclude_types,
        follow_execution=follow_execution,
        resume_after=resume_after,
        run_open=lambda: _run_open(tid, user_context),
    ):
        yield env
