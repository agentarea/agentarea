"""Task-event read side: catch-up (DB) + live (stream) — ADR-0018.

The frontend SSE and A2A streaming serve a task's event feed. This is a CQRS
read side, not a poll of the write model:

- **Catch-up** replays the history from the durable ``task_events`` table (a
  snapshot loader supplied by the caller, which owns DB access). A reconnecting
  client resumes after the last event it saw instead of replaying everything.
- **Live** tails a per-task Redis stream (``EventStream`` broadcast read) for
  events appended after the snapshot.

The two overlap by design; dedup by ``event_id`` makes the hand-off race-free
(an event committed during the snapshot read appears in both and is emitted
once). This replaces the previous 0.25s DB polling loop.

Producers (the worker) publish each task event to the per-task stream with
``publish_task_event``. Durable events are also persisted to ``task_events``
(history); ephemeral chunk events are stream-only (live tail, not replayed).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from agentarea_common.observability.propagation import current_traceparent

from .adapters.redis_streams import encode, topic_for
from .contract import TASK_STARTED, canonical_type
from .ports import EventStream, IntegrationEvent

logger = logging.getLogger(__name__)

# Live-tail buffer cap for a per-task stream. Full history lives in the DB, so
# this only needs to cover the snapshot->live hand-off plus recent live events.
TASK_STREAM_MAXLEN = 4096
# Refreshed on every append, so the stream of a finished or abandoned task
# expires instead of living in Redis forever.
TASK_STREAM_TTL_SECONDS = 24 * 60 * 60

_SOURCE = "agentarea-worker"


def task_stream_name(task_id: str) -> str:
    """Logical stream name for a task's event feed (``EventStream`` applies
    ``topic_for`` to get the physical Redis stream).
    """
    return f"task.{task_id}"


@dataclass(frozen=True)
class TaskEventEnvelope:
    """Normalized task event, the unit yielded by the feed.

    Both DB snapshot rows and live ``IntegrationEvent``s collapse to this shape
    so SSE/A2A consume one type regardless of source.
    """

    event_type: str
    event_id: str
    timestamp: str | None
    data: dict


def envelope_from_event(event: IntegrationEvent) -> TaskEventEnvelope:
    return TaskEventEnvelope(
        event_type=event.type,
        event_id=str(event.id),
        timestamp=event.time.isoformat() if event.time else None,
        data=dict(event.data or {}),
    )


async def publish_task_event(
    broker,
    *,
    task_id: str,
    event_type: str,
    data: dict,
    event_id: str | None = None,
    timestamp: str | None = None,
) -> None:
    """XADD one task event to the per-task live stream (bounded retention).

    Raises on failure; the caller decides whether the event is worth retrying.
    """
    event = IntegrationEvent(
        id=UUID(event_id) if event_id else uuid4(),
        type=event_type,
        source=_SOURCE,
        subject=task_id,
        time=datetime.fromisoformat(timestamp) if timestamp else datetime.now(UTC),
        traceparent=current_traceparent(),
        data=data,
    )
    await broker.submit(
        topic_for(task_stream_name(task_id)),
        encode(event),
        maxlen=TASK_STREAM_MAXLEN,
        ttl_seconds=TASK_STREAM_TTL_SECONDS,
    )


# A web conversation's feed stays open past a terminal event whose execution
# goes on: one waiting for a follow-up, or a stopped one still recording the
# call the stop interrupted.
_OPEN_EXECUTION_STATUSES = frozenset({"waiting", "settling"})


def _ends_feed(env: TaskEventEnvelope, terminal: frozenset[str], follow_execution: bool) -> bool:
    return canonical_type(env.event_type) in terminal and not (
        follow_execution and env.data.get("execution_status") in _OPEN_EXECUTION_STATUSES
    )


def _position(env: TaskEventEnvelope) -> tuple[datetime, str] | None:
    if not env.timestamp:
        return None
    moment = datetime.fromisoformat(env.timestamp)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment, env.event_id


def _is_after(env: TaskEventEnvelope, cursor: tuple[datetime, str] | None) -> bool:
    position = _position(env)
    return cursor is None or position is None or position > cursor


async def iter_task_event_feed(
    *,
    stream: EventStream,
    task_id: str,
    snapshot: Callable[[], AsyncIterator[TaskEventEnvelope]],
    terminal_types: frozenset[str],
    exclude_types: frozenset[str] = frozenset(),
    follow_execution: bool = False,
    resume_after: TaskEventEnvelope | None = None,
    run_open: Callable[[], Awaitable[bool]] | None = None,
    max_wall_time_seconds: float = 30 * 60,
) -> AsyncIterator[TaskEventEnvelope]:
    """Yield a task's events: history (catch-up) then live, dedup'd.

    Stops after a terminal event or ``max_wall_time_seconds`` (so a stuck task
    does not tail forever). ``snapshot`` yields the DB history in order.
    ``resume_after`` is the last durable event the client already has: the
    snapshot must start after it, and live entries at or before it are skipped.
    ``exclude_types`` are silently dropped (e.g. a consumer that does not want
    high-volume incremental ``llm.call.chunk`` events) — this never contains a
    terminal type, so it cannot suppress feed termination.
    ``follow_execution`` keeps a web conversation subscribed across completed
    turns whose workflow is still waiting for follow-up; A2A remains turn-scoped.

    A task's conversation can go on in a later run after one ended, so history
    is replayed in full: a terminal event closes the feed only when no later
    ``task.started`` opened a new run. ``run_open`` says whether a run that
    has not reported yet was started since; the feed then tails it.

    Membership tests are keyed on the canonical (dotted) event type. Rows and
    stream events already carry canonical names; ``canonical_type`` only strips a
    defensive ``workflow.`` prefix.
    """
    seen: set[str] = set()
    terminal = frozenset(canonical_type(t) for t in terminal_types)
    excluded = frozenset(canonical_type(t) for t in exclude_types)

    closed = resume_after is not None and _ends_feed(resume_after, terminal, follow_execution)
    cursor = _position(resume_after) if resume_after is not None else None

    async for env in snapshot():
        if canonical_type(env.event_type) in excluded or env.event_id in seen:
            continue
        seen.add(env.event_id)
        yield env
        if _ends_feed(env, terminal, follow_execution):
            closed = True
        elif canonical_type(env.event_type) == TASK_STARTED:
            closed = False
    if closed and (run_open is None or not await run_open()):
        return

    # Live tail from the start of the retained stream; dedup against the
    # snapshot. A wall-clock bound stops an open feed on a stuck task.
    loop = asyncio.get_event_loop()
    deadline = loop.time() + max_wall_time_seconds
    try:
        async with asyncio.timeout(max_wall_time_seconds):
            async for event in stream.read(stream=task_stream_name(task_id), from_offset="0"):
                env = envelope_from_event(event)
                if (
                    canonical_type(env.event_type) in excluded
                    or env.event_id in seen
                    or not _is_after(env, cursor)
                ):
                    continue
                seen.add(env.event_id)
                yield env
                if _ends_feed(env, terminal, follow_execution):
                    return
                if loop.time() >= deadline:
                    return
    except TimeoutError:
        logger.debug("Task event feed for %s reached wall-clock limit", task_id)
        return
