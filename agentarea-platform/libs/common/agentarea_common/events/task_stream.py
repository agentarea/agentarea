"""A task's events on the broker, and its feed: the log, then the tail (ADR-0043 §6, §8).

Write side: the ``record`` activity publishes each stored event of a run once to
``tasks.events`` (the envelope's subject is the task id, the ``seq`` extension
its position in the task log). Signals that matter only while the run is live
(a call started, reply chunks, progress) are broadcast on pub/sub
``tasks.live.{task_id}`` and never kept.

Read side, the feed of one task (SSE, A2A, CLI):

- **History** is the task log read from a position, by a snapshot loader the
  caller supplies (it owns DB access). A reconnecting client resumes after the
  last ``seq`` it saw.
- **Live** comes from the one tail of ``tasks.events`` (no consumer group) and the
  one pub/sub connection the process keeps (``TaskEventsHub``), filtered to the
  task. A feed subscribes before it reads history, so nothing written between
  the two is missed; an entry whose ``seq`` was already sent is dropped.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_common.broker.interface import BrokerClient, LiveChannels
from agentarea_common.broker.topics import BUS_RETENTION, TASK_EVENTS, task_live_channel
from agentarea_common.observability.propagation import current_traceparent

from .adapters.redis_streams import decode, encode
from .contract import LIVE_ONLY_TYPES, TASK_STARTED, canonical_type, require_known_type
from .ports import IntegrationEvent

logger = logging.getLogger(__name__)

_SOURCE = "agentarea-worker"
# Extension attributes of a task event: its position in the task log and its workspace.
SEQ_EXTENSION = "seq"
WORKSPACE_EXTENSION = "workspace"


@dataclass(frozen=True)
class TaskEventEnvelope:
    """One entry of a task's feed, from the log or from the broker.

    ``seq`` is the entry's position in the task log; a live-only signal has none.
    """

    event_type: str
    event_id: str
    timestamp: str | None
    data: dict
    seq: int | None = None


def task_event(
    *,
    task_id: str,
    workspace_id: str | None,
    event_type: str,
    event_id: str,
    timestamp: datetime,
    data: Mapping[str, Any],
    seq: int | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> IntegrationEvent:
    """The broker envelope of one task event; a live-only signal may name no workspace."""
    extensions: dict[str, str] = {}
    if workspace_id is not None:
        extensions[WORKSPACE_EXTENSION] = workspace_id
    if seq is not None:
        extensions[SEQ_EXTENSION] = str(seq)
    return IntegrationEvent(
        id=UUID(event_id),
        type=require_known_type(event_type),
        source=_SOURCE,
        subject=task_id,
        time=timestamp,
        correlation_id=correlation_id,
        causation_id=causation_id,
        traceparent=current_traceparent(),
        data=dict(data),
        extensions=extensions,
    )


async def publish_task_event(broker: BrokerClient, event: IntegrationEvent) -> None:
    """Put a stored task event on ``tasks.events``; live-only signals go to pub/sub instead."""
    if event.type in LIVE_ONLY_TYPES:
        raise ValueError(f"{event.type} is live-only; broadcast it with broadcast_live")
    await broker.submit(TASK_EVENTS, encode(event), retention=BUS_RETENTION)


async def broadcast_live(broker: BrokerClient, event: IntegrationEvent) -> None:
    """Broadcast a live-only signal to the feeds open on its task; nothing is kept."""
    if event.type not in LIVE_ONLY_TYPES:
        raise ValueError(f"{event.type} is stored; publish it with publish_task_event")
    if event.subject is None:
        raise ValueError(f"live signal {event.id} names no task")
    await broker.notify(task_live_channel(event.subject), encode(event))


def envelope_from_event(event: IntegrationEvent) -> TaskEventEnvelope:
    seq = event.extensions.get(SEQ_EXTENSION)
    return TaskEventEnvelope(
        event_type=event.type,
        event_id=str(event.id),
        timestamp=event.time.isoformat() if event.time else None,
        data=dict(event.data or {}),
        seq=int(seq) if seq is not None else None,
    )


class TaskEventsHub:
    """One tail of ``tasks.events`` and one pub/sub connection, shared by a process's feeds."""

    def __init__(self, broker: BrokerClient, *, block_ms: int = 5000) -> None:
        self._broker = broker
        self._block_ms = block_ms
        self._queues: dict[str, set[asyncio.Queue[TaskEventEnvelope]]] = {}
        self._lock = asyncio.Lock()
        self._tail: asyncio.Task[None] | None = None
        self._live: LiveChannels | None = None
        self._listener: asyncio.Task[None] | None = None

    @asynccontextmanager
    async def subscribe(self, task_id: str) -> AsyncIterator[asyncio.Queue[TaskEventEnvelope]]:
        """A queue that receives every event of the task published from now on."""
        queue: asyncio.Queue[TaskEventEnvelope] = asyncio.Queue()
        async with self._lock:
            live = await self._start()
            first = task_id not in self._queues
            self._queues.setdefault(task_id, set()).add(queue)
            if first:
                await live.subscribe(task_live_channel(task_id))
        try:
            yield queue
        finally:
            async with self._lock:
                queues = self._queues.get(task_id, set())
                queues.discard(queue)
                if not queues:
                    self._queues.pop(task_id, None)
                    await live.unsubscribe(task_live_channel(task_id))

    async def aclose(self) -> None:
        for task in (self._tail, self._listener):
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self._tail = self._listener = None
        if self._live is not None:
            await self._live.aclose()
            self._live = None

    async def _start(self) -> LiveChannels:
        if self._tail is None or self._tail.done():
            # From the newest entry now: a feed subscribed before it reads its
            # history, so anything published after this is in the tail.
            cursor = await self._broker.last_id(TASK_EVENTS)
            self._tail = asyncio.create_task(self._run_tail(cursor), name="tasks-events-tail")
        if self._live is None:
            self._live = await self._broker.open_live()
            self._listener = asyncio.create_task(self._run_live(self._live), name="tasks-live")
        return self._live

    async def _run_tail(self, cursor: str) -> None:
        while True:
            try:
                cursor, messages = await self._broker.tail(
                    TASK_EVENTS, last_id=cursor, block_ms=self._block_ms, count=500
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("Tail of %s failed; retrying", TASK_EVENTS, exc_info=True)
                await asyncio.sleep(1)
                continue
            for message in messages:
                try:
                    event = decode(message.fields)
                except Exception:
                    logger.error(
                        "Undecodable entry %s on %s; skipped",
                        message.id,
                        TASK_EVENTS,
                        exc_info=True,
                    )
                    continue
                self._dispatch(event)

    async def _run_live(self, live: LiveChannels) -> None:
        while True:
            try:
                received = await live.next_message(1.0)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("Live task signals failed; retrying", exc_info=True)
                await asyncio.sleep(1)
                continue
            if received is None:
                continue
            channel, fields = received
            try:
                event = decode(fields)
            except Exception:
                logger.error("Undecodable live signal on %s; skipped", channel, exc_info=True)
                continue
            self._dispatch(event)

    def _dispatch(self, event: IntegrationEvent) -> None:
        queues = self._queues.get(event.subject or "")
        if not queues:
            return
        envelope = envelope_from_event(event)
        for queue in queues:
            queue.put_nowait(envelope)


# A web conversation's feed stays open past a terminal event whose execution
# goes on: one waiting for a follow-up, or a stopped one still recording the
# call the stop interrupted.
_OPEN_EXECUTION_STATUSES = frozenset({"waiting", "settling"})


def _ends_feed(env: TaskEventEnvelope, terminal: frozenset[str], follow_execution: bool) -> bool:
    return canonical_type(env.event_type) in terminal and not (
        follow_execution and env.data.get("execution_status") in _OPEN_EXECUTION_STATUSES
    )


async def iter_task_event_feed(
    *,
    hub: TaskEventsHub,
    task_id: str,
    snapshot: Callable[[], AsyncIterator[TaskEventEnvelope]],
    terminal_types: frozenset[str],
    exclude_types: frozenset[str] = frozenset(),
    follow_execution: bool = False,
    resume_after: TaskEventEnvelope | None = None,
    run_open: Callable[[], Awaitable[bool]] | None = None,
    max_wall_time_seconds: float = 30 * 60,
    live_view: Callable[[TaskEventEnvelope], Awaitable[TaskEventEnvelope]] | None = None,
) -> AsyncIterator[TaskEventEnvelope]:
    """Yield a task's feed: its log after ``resume_after``, then live entries.

    Stops after a terminal event or ``max_wall_time_seconds`` (so a stuck task
    does not tail forever). ``snapshot`` yields the log entries after
    ``resume_after`` in ``seq`` order. ``exclude_types`` are dropped (e.g.
    ``llm.call.chunk`` for a consumer that does not want it); it never holds a
    terminal type. ``follow_execution`` keeps a web conversation subscribed
    across completed turns whose workflow still waits for a follow-up; A2A stays
    turn-scoped.

    A task's conversation can go on in a later run after one ended, so history
    is replayed in full: a terminal event closes the feed only when no later
    ``task.started`` opened a new run. ``run_open`` says whether a run that has
    not reported yet was started since; the feed then tails it. ``live_view``
    turns a live entry, as the broker carries it, into what this caller sees.
    """
    terminal = frozenset(canonical_type(t) for t in terminal_types)
    excluded = frozenset(canonical_type(t) for t in exclude_types)
    closed = resume_after is not None and _ends_feed(resume_after, terminal, follow_execution)
    last_seq = resume_after.seq if resume_after is not None and resume_after.seq is not None else -1
    async with hub.subscribe(task_id) as live:
        async for env in snapshot():
            if env.seq is not None:
                if env.seq <= last_seq:
                    continue
                last_seq = env.seq
            if canonical_type(env.event_type) in excluded:
                continue
            yield env
            if _ends_feed(env, terminal, follow_execution):
                closed = True
            elif canonical_type(env.event_type) == TASK_STARTED:
                closed = False
        if closed and (run_open is None or not await run_open()):
            return
        try:
            async with asyncio.timeout(max_wall_time_seconds):
                while True:
                    env = await live.get()
                    if env.seq is not None:
                        if env.seq <= last_seq:
                            continue
                        last_seq = env.seq
                    if canonical_type(env.event_type) in excluded:
                        continue
                    if live_view is not None:
                        env = await live_view(env)
                    yield env
                    if _ends_feed(env, terminal, follow_execution):
                        return
        except TimeoutError:
            logger.debug("Task event feed for %s reached wall-clock limit", task_id)
