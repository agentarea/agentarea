"""Task-event read side: catch-up (DB) + live (stream) — ADR-0018.

The frontend SSE and A2A streaming serve a task's event feed. This is a CQRS
read side, not a poll of the write model:

- **Catch-up** replays the full history from the durable ``task_events`` table
  (a snapshot loader supplied by the caller, which owns DB access).
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
from uuid import uuid4

from .adapters.redis_streams import encode, topic_for
from .ports import EventStream, IntegrationEvent

logger = logging.getLogger(__name__)

# Live-tail buffer cap for a per-task stream. Full history lives in the DB, so
# this only needs to cover the snapshot->live hand-off plus recent live events.
TASK_STREAM_MAXLEN = 4096

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

    Best-effort: a publish failure is logged, never raised — the durable record
    is the DB, and live tailing is at-most-once by contract.
    """
    try:
        try:
            occurred_at = datetime.fromisoformat(timestamp) if timestamp else datetime.now(UTC)
        except ValueError:
            occurred_at = datetime.now(UTC)

        event = IntegrationEvent(
            id=event_id or str(uuid4()),
            type=event_type,
            source=_SOURCE,
            subject=task_id,
            time=occurred_at,
            data=data,
        )
        await broker.submit(
            topic_for(task_stream_name(task_id)),
            encode(event),
            maxlen=TASK_STREAM_MAXLEN,
        )
    except Exception:
        logger.exception("Failed to publish task event %s for task %s", event_type, task_id)


async def iter_task_event_feed(
    *,
    stream: EventStream,
    task_id: str,
    snapshot: Callable[[], Awaitable[list[TaskEventEnvelope]]],
    terminal_types: frozenset[str],
    exclude_types: frozenset[str] = frozenset(),
    max_wall_time_seconds: float = 30 * 60,
) -> AsyncIterator[TaskEventEnvelope]:
    """Yield a task's events: full history (catch-up) then live, dedup'd.

    Stops after a terminal event or ``max_wall_time_seconds`` (so a stuck task
    does not tail forever). ``snapshot`` returns the DB history in order.
    ``exclude_types`` are silently dropped (e.g. a consumer that does not want
    high-volume incremental ``LLMCallChunk`` events) — this never contains a
    terminal type, so it cannot suppress feed termination.
    """
    seen: set[str] = set()

    for env in await snapshot():
        if env.event_type in exclude_types or env.event_id in seen:
            continue
        seen.add(env.event_id)
        yield env
        if env.event_type in terminal_types:
            return

    # Live tail from the start of the retained stream; dedup against the
    # snapshot. A wall-clock bound stops an open feed on a stuck task.
    loop = asyncio.get_event_loop()
    deadline = loop.time() + max_wall_time_seconds
    try:
        async with asyncio.timeout(max_wall_time_seconds):
            async for event in stream.read(stream=task_stream_name(task_id), from_offset="0"):
                env = envelope_from_event(event)
                if env.event_type in exclude_types or env.event_id in seen:
                    continue
                seen.add(env.event_id)
                yield env
                if env.event_type in terminal_types:
                    return
                if loop.time() >= deadline:
                    return
    except TimeoutError:
        logger.debug("Task event feed for %s reached wall-clock limit", task_id)
        return
