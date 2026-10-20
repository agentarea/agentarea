"""The workspace events feed: every event of the streams a caller may read, and its live tail.

A page reads the feed newest first, then keeps one SSE connection open. The
events view and the router announce what they wrote on pub/sub
``streams.live.{workspace_id}`` (``agentarea_streams.infrastructure.live``);
this process keeps one connection for every open page (``EventNoticesHub``)
and, for each notice on a stream the page may read, reads the event back under
the page's filter: ``event.recorded`` carries it whole, ``event.processing``
what the platform did with it since.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Collection
from contextlib import AbstractAsyncContextManager
from typing import Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.broker.redis_streams import RedisStreamsBroker
from agentarea_common.config import RedisSettings, get_settings
from agentarea_common.utils.types import UtcDatetime
from agentarea_streams.domain import ENVELOPE_VERSION, Verdict
from agentarea_streams.domain.feed import FeedFilter, RoutedEvent
from agentarea_streams.domain.processing import Processing, ProcessingTask
from agentarea_streams.infrastructure.event_repository import FACET_CAP, StreamEventRepository
from agentarea_streams.infrastructure.live import EventNotice, EventNoticesHub, NoticeKind
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_triggers.infrastructure.reaction_feed_repository import ReactionFeedRepository
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_hub: EventNoticesHub | None = None


def event_notices_hub() -> EventNoticesHub:
    global _hub
    if _hub is None:
        settings = get_settings()
        if not isinstance(settings.broker, RedisSettings):
            raise RuntimeError(
                "The events feed reads the Redis broker; set AGENTAREA_BROKER=redis "
                + f"(current: {settings.broker.BROKER})"
            )
        _hub = EventNoticesHub(
            RedisStreamsBroker(settings.broker.REDIS_URL, namespace=settings.streams.NAMESPACE)
        )
    return _hub


async def close_event_notices_hub() -> None:
    global _hub
    if _hub is not None:
        await _hub.aclose()
        _hub = None


class FeedEventResponse(BaseModel):
    """An event's envelope without its body, and what the platform did with it."""

    sequence: int
    v: int = ENVELOPE_VERSION
    event_id: UUID
    stream_id: UUID
    source_id: UUID | None
    source_type: str | None
    kind: str
    key: str
    session_key: str | None
    sender: str | None
    received_at: UtcDatetime
    occurred_at: UtcDatetime
    depth: int
    correlation_id: str | None
    causation_id: str | None
    attachments: int = Field(description="How many files the event carries.")
    processing: Processing


class FeedFacetsResponse(BaseModel):
    streams: dict[UUID, int] = Field(description="Events per stream under the other filters.")
    source_types: dict[str, int] = Field(
        description="Events per source type under the other filters."
    )
    capped: bool = Field(
        default=False,
        description=(
            "Under a filter other than stream and source type the counts stop after the "
            f"first {FACET_CAP} matching events; true when more match, so each count is a "
            "lower bound."
        ),
    )


class WorkspaceEventPage(BaseModel):
    events: list[FeedEventResponse]
    next_before: int | None = Field(
        default=None, description="Pass as ?before= for older events; null at the start."
    )
    facets: FeedFacetsResponse | None = Field(
        default=None, description="On the first page only (no ?before=)."
    )


def _started_task(row: Any) -> UUID | None:
    """The task the reaction started; its status turns ``failed`` when that task fails."""
    return row.task_id if row.verdict == Verdict.REACTED.value else None


async def feed_items(
    session: AsyncSession, user_context: UserContext, events: list[RoutedEvent]
) -> list[FeedEventResponse]:
    """The events as the feed shows them, each with the tasks it started and their status."""
    tasks_of: dict[UUID, list[UUID]] = {}
    for row in await ReactionFeedRepository(session, user_context).list_for_event_ids(
        [e.id for e in events]
    ):
        task_id = _started_task(row)
        if row.event_id is not None and task_id is not None:
            tasks_of.setdefault(row.event_id, []).append(task_id)
    statuses = await TaskRepository(session, user_context).statuses(
        [t for ids in tasks_of.values() for t in ids]
    )
    items = []
    for e in events:
        processing = e.processing()
        processing.tasks = [
            ProcessingTask(id=t, status=statuses[t])
            for t in tasks_of.get(e.id, [])
            if t in statuses
        ]
        items.append(
            FeedEventResponse(
                sequence=e.sequence,
                event_id=e.id,
                stream_id=e.stream_id,
                source_id=e.source_id,
                source_type=e.source_type,
                kind=e.type,
                key=e.event_key,
                session_key=e.session_key,
                sender=e.sender,
                received_at=e.received_at,
                occurred_at=e.time,
                depth=e.depth,
                correlation_id=e.correlation_id,
                causation_id=e.causation_id,
                attachments=len(e.attachments),
                processing=processing,
            )
        )
    return items


async def read_feed_item(
    session: AsyncSession,
    user_context: UserContext,
    feed_filter: FeedFilter,
    streams: Collection[UUID],
    event_id: UUID,
) -> FeedEventResponse | None:
    """One event of the feed, if it is in ``streams`` and passes the filter."""
    rows = await StreamEventRepository(session, user_context).read_feed(
        feed_filter.model_copy(update={"event_id": event_id}), streams, before=None, limit=1
    )
    if not rows:
        return None
    (item,) = await feed_items(session, user_context, rows)
    return item


def sse_frame(event_type: str, data: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


async def iter_live_feed(
    *,
    subscribe: Callable[[], AbstractAsyncContextManager[Any]],
    streams: Collection[UUID],
    load: Callable[[UUID], Awaitable[FeedEventResponse | None]],
) -> AsyncGenerator[str, None]:
    """SSE frames for the notices on ``streams`` whose event passes the page's filter."""
    visible = set(streams)
    async with subscribe() as queue:
        # A comment at once: the page knows it is live without waiting for an event.
        yield ": subscribed\n\n"
        while True:
            notice: EventNotice | None = await queue.get()
            if notice is None:
                return
            if notice.stream_id not in visible:
                continue
            item = await load(notice.event_id)
            if item is None:
                continue
            if notice.kind is NoticeKind.RECORDED:
                yield sse_frame(NoticeKind.RECORDED.value, item.model_dump(mode="json"))
            else:
                yield sse_frame(
                    NoticeKind.PROCESSING.value,
                    {
                        "event_id": str(item.event_id),
                        "processing": item.processing.model_dump(mode="json"),
                    },
                )
