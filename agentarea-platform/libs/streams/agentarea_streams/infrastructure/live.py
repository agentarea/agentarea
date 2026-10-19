"""Live notices for the events pages: pub/sub ``streams.live.{workspace_id}``, never kept.

The events view announces an event once it is recorded, the router each time it
routed it or recorded a reaction. A notice names the event only; the page's
connection reads the rest from the read model, as the caller may see it.
``EventNoticesHub`` is a process's one pub/sub connection, shared by its pages.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from agentarea_common.broker.interface import BrokerClient, LiveChannels
from agentarea_common.broker.topics import STREAMS_LIVE, streams_live_channel

from ..domain.models import StreamEvent

logger = logging.getLogger(__name__)

# Notices a page has not taken yet; past it, its stream ends and it reads the feed again.
QUEUE_LIMIT = 1000


class NoticeKind(StrEnum):
    RECORDED = "event.recorded"
    PROCESSING = "event.processing"


@dataclass(frozen=True)
class EventNotice:
    kind: NoticeKind
    event_id: UUID
    stream_id: UUID


class BrokerEventNotices:
    """The streams ``EventNotices`` port over the broker's pub/sub."""

    def __init__(self, broker: BrokerClient) -> None:
        self._broker = broker

    async def recorded(self, event: StreamEvent) -> None:
        await self._send(NoticeKind.RECORDED, event)

    async def processing(self, event: StreamEvent) -> None:
        await self._send(NoticeKind.PROCESSING, event)

    async def _send(self, kind: NoticeKind, event: StreamEvent) -> None:
        await self._broker.notify(
            streams_live_channel(event.workspace_id),
            {"type": kind.value, "event_id": str(event.id), "stream_id": str(event.stream_id)},
        )


class EventNoticesHub:
    """One pub/sub connection, subscribed to the workspaces whose pages are open."""

    def __init__(self, broker: BrokerClient) -> None:
        self._broker = broker
        self._queues: dict[str, set[asyncio.Queue[EventNotice | None]]] = {}
        self._lock = asyncio.Lock()
        self._live: LiveChannels | None = None
        self._listener: asyncio.Task[None] | None = None

    @asynccontextmanager
    async def subscribe(
        self, workspace_id: str
    ) -> AsyncIterator[asyncio.Queue[EventNotice | None]]:
        """A queue of the workspace's notices from now on; ``None`` once the hub closes."""
        queue: asyncio.Queue[EventNotice | None] = asyncio.Queue(maxsize=QUEUE_LIMIT)
        async with self._lock:
            live = await self._start()
            first = workspace_id not in self._queues
            self._queues.setdefault(workspace_id, set()).add(queue)
            if first:
                await live.subscribe(streams_live_channel(workspace_id))
        try:
            yield queue
        finally:
            async with self._lock:
                queues = self._queues.get(workspace_id, set())
                queues.discard(queue)
                if not queues:
                    self._queues.pop(workspace_id, None)
                    if self._live is live:
                        await live.unsubscribe(streams_live_channel(workspace_id))

    async def aclose(self) -> None:
        # A page still open ends its stream and reconnects to a process that serves it.
        for queues in self._queues.values():
            for queue in queues:
                _end(queue)
        if self._listener is not None:
            self._listener.cancel()
            await asyncio.gather(self._listener, return_exceptions=True)
            self._listener = None
        if self._live is not None:
            await self._live.aclose()
            self._live = None

    async def _start(self) -> LiveChannels:
        if self._live is None:
            self._live = await self._broker.open_live()
            self._listener = asyncio.create_task(self._run(self._live), name="streams-live")
        return self._live

    async def _run(self, live: LiveChannels) -> None:
        prefix = f"{STREAMS_LIVE}."
        while True:
            try:
                received = await live.next_message(1.0)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("Live event notices failed; retrying", exc_info=True)
                await asyncio.sleep(1)
                continue
            if received is None:
                continue
            channel, fields = received
            try:
                notice = EventNotice(
                    kind=NoticeKind(fields["type"]),
                    event_id=UUID(fields["event_id"]),
                    stream_id=UUID(fields["stream_id"]),
                )
            except Exception:
                logger.error("Unreadable event notice on %s; skipped", channel, exc_info=True)
                continue
            self._dispatch(channel.removeprefix(prefix), notice)

    def _dispatch(self, workspace_id: str, notice: EventNotice) -> None:
        for queue in self._queues.get(workspace_id, ()):
            try:
                queue.put_nowait(notice)
            except asyncio.QueueFull:
                logger.warning(
                    "An events page of workspace %s is %d notices behind; its stream ends",
                    workspace_id,
                    QUEUE_LIMIT,
                )
                _end(queue)


def _end(queue: asyncio.Queue[EventNotice | None]) -> None:
    """Make ``None`` the next thing the page reads: its stream ends."""
    while not queue.empty():
        queue.get_nowait()
    queue.put_nowait(None)
