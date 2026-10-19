"""The events read model: what the bus carried, by stream. Never commits; the caller does.

Written by the ``events-view`` group, and by the router: what it did with each
event (``mark_routed``, ``mark_reactions``), and the event itself when it gets
there before the events view. Read by the events page and agents. Nothing reads
it to decide what to fire.

Readers page a stream oldest first by ``sequence > after``. A sequence is taken
at insert but becomes visible at commit, so two concurrent inserts into one
stream could commit out of order and the earlier one fall behind a cursor for
good. Each insert therefore holds its stream's insert lock until its
transaction ends: within a stream, commit order is sequence order.
"""

import logging
from collections import Counter
from collections.abc import Collection
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from sqlalchemy import ColumnElement, and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.errors import StreamNotFoundError
from ..domain.feed import FeedFacets, FeedFilter, RoutedEvent
from ..domain.models import Attachment, ReactionTally, RecordedEvent, StreamEvent
from ..domain.platform import PLATFORM_SOURCE_TYPE
from ..domain.processing import ProcessingStatus
from .orm import StreamEventCountORM, StreamEventORM, StreamORM

logger = logging.getLogger(__name__)

_FOREIGN_KEY_VIOLATION = "23503"
#: First key of the two-key advisory lock on a stream's inserts; the second is the stream.
_INSERT_LOCK_CLASS = 0x53455131
#: Under filters the rollup cannot answer, the facets count this many matching events at most.
FACET_CAP = 1000
#: ``stream_event_counts.source_type`` of an event with none.
_NO_SOURCE_TYPE = ""


def _envelope(row: StreamEventORM) -> dict[str, Any]:
    return {
        "id": row.event_id,
        "type": row.kind,
        "source": row.source,
        "time": row.occurred_at,
        "subject": row.subject,
        "correlation_id": row.correlation_id,
        "causation_id": row.causation_id,
        "data": row.data,
        "stream_id": row.stream_id,
        "workspace_id": row.workspace_id,
        "created_by": row.created_by,
        "sequence": row.sequence,
        "event_key": row.event_key,
        "received_at": row.received_at,
        "depth": row.depth,
        "source_id": row.source_id,
        "source_type": row.source_type,
        "session_key": row.session_key,
        "sender": row.sender,
        "attachments": [Attachment.model_validate(a) for a in row.attachments],
    }


def to_recorded(row: StreamEventORM) -> RecordedEvent:
    return RecordedEvent(**_envelope(row))


def to_routed(row: StreamEventORM) -> RoutedEvent:
    return RoutedEvent(
        **_envelope(row),
        routed_at=row.routed_at,
        subscribers=row.subscribers,
        reacted=row.reacted,
        skipped=row.skipped,
        errors=row.errors,
    )


_E = StreamEventORM
_ROUTED = _E.routed_at.is_not(None)
_DONE = and_(_ROUTED, _E.errors == 0, _E.reacted >= _E.subscribers, _E.reacted > 0)
# Mirrors ``processing_status``; the feed suite holds the two to the same answer.
_RESULT: dict[ProcessingStatus, ColumnElement[bool]] = {
    ProcessingStatus.QUEUED: _E.routed_at.is_(None),
    ProcessingStatus.NO_HANDLERS: and_(_ROUTED, _E.subscribers == 0, _E.reacted == 0),
    ProcessingStatus.ERROR: and_(_ROUTED, _E.errors > 0),
    ProcessingStatus.PROCESSING: and_(_ROUTED, _E.errors == 0, _E.reacted < _E.subscribers),
    ProcessingStatus.SKIPPED: and_(_DONE, _E.skipped == _E.reacted),
    ProcessingStatus.HANDLED: and_(_DONE, _E.skipped < _E.reacted),
}


def _feed_conditions(
    feed_filter: FeedFilter, *, facet: str | None = None
) -> list[ColumnElement[bool]]:
    """The filter as conditions; a facet's own filter is left out of its counts.

    The counts include the platform's own events either way, so a view without
    them still says how many there are.
    """
    f = feed_filter
    conditions: list[ColumnElement[bool]] = []
    if f.stream_id is not None and facet != "stream":
        conditions.append(_E.stream_id == f.stream_id)
    if f.source_type is not None and facet != "source_type":
        conditions.append(_E.source_type == f.source_type)
    if not f.platform and facet is None:
        conditions.append(_E.source_type.is_distinct_from(PLATFORM_SOURCE_TYPE))
    return conditions + _other_conditions(f)


def _other_conditions(f: FeedFilter) -> list[ColumnElement[bool]]:
    """Every filter but the stream, the source type and the platform switch."""
    conditions: list[ColumnElement[bool]] = []
    if (exact := f.exact_kind()) is not None:
        conditions.append(_E.kind == exact)
    if (prefix := f.kind_prefix()) is not None:
        conditions.append(_E.kind.startswith(prefix, autoescape=True))
    if f.sender is not None:
        conditions.append(_E.sender == f.sender)
    if f.session_key is not None:
        conditions.append(_E.session_key == f.session_key)
    if f.result is not None:
        conditions.append(_RESULT[f.result])
    if f.since is not None:
        conditions.append(_E.received_at >= f.since)
    if f.until is not None:
        conditions.append(_E.received_at < f.until)
    if f.event_id is not None:
        conditions.append(_E.event_id == f.event_id)
    return conditions


def _day(at: datetime) -> date:
    return at.astimezone(UTC).date()


class StreamEventRepository:
    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.user_context = user_context

    def _in_workspace(self) -> ColumnElement[bool]:
        return StreamEventORM.workspace_id == self.user_context.workspace_id

    async def record(self, event: StreamEvent) -> bool:
        """Insert the event once; False for a repeat or a stream deleted meanwhile."""
        self._require_own(event)
        seen = await self.session.execute(
            select(StreamEventORM.sequence)
            .where(StreamEventORM.event_id == event.id, self._in_workspace())
            .limit(1)
        )
        if seen.first() is not None:
            return False
        return await self._insert(event)

    async def mark_routed(self, event: StreamEvent, subscribers: int, *, at: datetime) -> bool:
        """The router matched ``subscribers`` subscriptions; the first routing time is kept.

        Writes the event itself when the events view has not yet, and says so.
        """
        self._require_own(event)
        if await self._insert(event, routed_at=at, subscribers=subscribers):
            return True
        await self.session.execute(
            update(StreamEventORM)
            .where(
                StreamEventORM.event_id == event.id,
                StreamEventORM.received_at == event.received_at,
                self._in_workspace(),
            )
            .values(
                routed_at=func.coalesce(StreamEventORM.routed_at, at),
                subscribers=subscribers,
            )
        )
        return False

    async def mark_reactions(self, event: StreamEvent, tally: ReactionTally) -> None:
        self._require_own(event)
        await self.session.execute(
            update(StreamEventORM)
            .where(
                StreamEventORM.event_id == event.id,
                StreamEventORM.received_at == event.received_at,
                self._in_workspace(),
            )
            .values(reacted=tally.reacted, skipped=tally.skipped, errors=tally.errors)
        )

    def _require_own(self, event: StreamEvent) -> None:
        if event.workspace_id != self.user_context.workspace_id:
            raise ValueError(
                f"event {event.id} belongs to workspace {event.workspace_id}, "
                + f"not {self.user_context.workspace_id}"
            )

    async def _insert(self, event: StreamEvent, **routing: Any) -> bool:
        await self.session.execute(
            select(
                func.pg_advisory_xact_lock(_INSERT_LOCK_CLASS, func.hashtext(str(event.stream_id)))
            )
        )
        try:
            async with self.session.begin_nested():
                inserted = await self.session.execute(
                    pg_insert(StreamEventORM)
                    .values(
                        received_at=event.received_at,
                        stream_id=event.stream_id,
                        event_id=event.id,
                        event_key=event.event_key,
                        kind=event.type,
                        source=event.source,
                        subject=event.subject,
                        occurred_at=event.time,
                        correlation_id=event.correlation_id,
                        causation_id=event.causation_id,
                        source_id=event.source_id,
                        source_type=event.source_type,
                        session_key=event.session_key,
                        sender=event.sender,
                        depth=event.depth,
                        data=event.data,
                        attachments=[a.model_dump(mode="json") for a in event.attachments],
                        workspace_id=event.workspace_id,
                        created_by=event.created_by,
                        **routing,
                    )
                    .on_conflict_do_nothing(index_elements=["event_id", "received_at"])
                    .returning(StreamEventORM.sequence)
                )
                if inserted.scalar_one_or_none() is None:
                    return False
                await self._count(event)
                return True
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) != _FOREIGN_KEY_VIOLATION:
                raise
            logger.info(
                "Event %s not recorded: stream %s no longer exists", event.id, event.stream_id
            )
            return False

    async def _count(self, event: StreamEvent) -> None:
        """One more event in its stream's day; under the stream's insert lock, like the row."""
        counts = StreamEventCountORM
        await self.session.execute(
            pg_insert(counts)
            .values(
                workspace_id=event.workspace_id,
                created_by=event.created_by,
                stream_id=event.stream_id,
                day=_day(event.received_at),
                source_type=event.source_type or _NO_SOURCE_TYPE,
                count=1,
            )
            .on_conflict_do_update(
                index_elements=[
                    counts.workspace_id,
                    counts.stream_id,
                    counts.day,
                    counts.source_type,
                ],
                set_={"count": counts.count + 1},
            )
        )

    async def read_by_id(self, event_id: UUID) -> RecordedEvent | None:
        """The event with this id in this workspace, whichever stream holds it."""
        result = await self.session.execute(
            select(StreamEventORM)
            .where(StreamEventORM.event_id == event_id, self._in_workspace())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return to_recorded(row) if row is not None else None

    async def read_routed(self, event_id: UUID) -> RoutedEvent | None:
        result = await self.session.execute(
            select(StreamEventORM)
            .where(StreamEventORM.event_id == event_id, self._in_workspace())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return to_routed(row) if row is not None else None

    async def read_feed(
        self,
        feed_filter: FeedFilter,
        streams: Collection[UUID],
        *,
        before: int | None,
        limit: int,
    ) -> list[RoutedEvent]:
        """Newest first, of ``streams`` only (those the caller may read)."""
        stmt = select(StreamEventORM).where(
            self._in_workspace(), _E.stream_id.in_(list(streams)), *_feed_conditions(feed_filter)
        )
        if before is not None:
            stmt = stmt.where(_E.sequence < before)
        result = await self.session.execute(stmt.order_by(_E.sequence.desc()).limit(limit))
        return [to_routed(row) for row in result.scalars().all()]

    async def feed_facets(
        self, feed_filter: FeedFilter, streams: Collection[UUID], *, cap: int = FACET_CAP
    ) -> FeedFacets:
        """Events per stream and per source type, each facet under the other filters.

        Filtered by no more than stream and source type, they come from the
        rollup. Any other filter counts the rows themselves, up to ``cap`` of them.
        """
        if _other_conditions(feed_filter):
            return await self._capped_facets(feed_filter, streams, cap)
        return await self._rolled_up_facets(feed_filter, streams)

    async def _rolled_up_facets(
        self, feed_filter: FeedFilter, streams: Collection[UUID]
    ) -> FeedFacets:
        counts = StreamEventCountORM
        visible: list[ColumnElement[bool]] = [
            counts.workspace_id == self.user_context.workspace_id,
            counts.stream_id.in_(list(streams)),
        ]
        by_stream = select(counts.stream_id, func.sum(counts.count)).where(*visible)
        if feed_filter.source_type is not None:
            by_stream = by_stream.where(counts.source_type == feed_filter.source_type)
        by_source = select(counts.source_type, func.sum(counts.count)).where(
            *visible, counts.source_type != _NO_SOURCE_TYPE
        )
        if feed_filter.stream_id is not None:
            by_source = by_source.where(counts.stream_id == feed_filter.stream_id)
        stream_rows = await self.session.execute(by_stream.group_by(counts.stream_id))
        source_rows = await self.session.execute(by_source.group_by(counts.source_type))
        return FeedFacets(
            streams={stream: int(n) for stream, n in stream_rows.tuples().all()},
            source_types={source: int(n) for source, n in source_rows.tuples().all()},
        )

    async def _capped_facets(
        self, feed_filter: FeedFilter, streams: Collection[UUID], cap: int
    ) -> FeedFacets:
        """Both facets from one scan that stops after ``cap`` matching events.

        The filter columns have no index, so a count per value would read the
        workspace once per value. Past ``cap`` the counts are of the events
        read so far: each is then a lower bound, and ``capped`` says so.
        """
        f = feed_filter
        either: list[ColumnElement[bool]] = []
        if f.stream_id is not None and f.source_type is not None:
            either.append(or_(_E.stream_id == f.stream_id, _E.source_type == f.source_type))
        matched = (
            select(_E.stream_id, _E.source_type)
            .where(
                self._in_workspace(),
                _E.stream_id.in_(list(streams)),
                *either,
                *_other_conditions(f),
            )
            .limit(cap + 1)
            .subquery("matched")
        )
        rows = await self.session.execute(
            select(matched.c.stream_id, matched.c.source_type, func.count()).group_by(
                matched.c.stream_id, matched.c.source_type
            )
        )
        by_stream: Counter[UUID] = Counter()
        by_source: Counter[str] = Counter()
        total = 0
        for stream_id, source_type, n in rows.tuples().all():
            total += n
            if f.source_type is None or source_type == f.source_type:
                by_stream[stream_id] += n
            if source_type is not None and (f.stream_id is None or stream_id == f.stream_id):
                by_source[source_type] += n
        return FeedFacets(streams=dict(by_stream), source_types=dict(by_source), capped=total > cap)

    async def read_after(self, stream_id: UUID, after: int, limit: int) -> list[RecordedEvent]:
        result = await self.session.execute(
            select(StreamEventORM)
            .where(
                StreamEventORM.stream_id == stream_id,
                StreamEventORM.sequence > after,
                self._in_workspace(),
            )
            .order_by(StreamEventORM.sequence)
            .limit(limit)
        )
        return [to_recorded(row) for row in result.scalars().all()]

    async def read_since(
        self, stream_id: UUID, since: datetime, after: int, limit: int
    ) -> list[RecordedEvent]:
        """Oldest first: received at or after ``since`` and past the ``after`` position."""
        result = await self.session.execute(
            select(StreamEventORM)
            .where(
                StreamEventORM.stream_id == stream_id,
                StreamEventORM.received_at >= since,
                StreamEventORM.sequence > after,
                self._in_workspace(),
            )
            .order_by(StreamEventORM.sequence)
            .limit(limit)
        )
        return [to_recorded(row) for row in result.scalars().all()]

    async def read_before(
        self, stream_id: UUID, before: int | None, limit: int
    ) -> list[RecordedEvent]:
        """Newest first; ``before=None`` starts at the newest event."""
        stmt = select(StreamEventORM).where(
            StreamEventORM.stream_id == stream_id, self._in_workspace()
        )
        if before is not None:
            stmt = stmt.where(StreamEventORM.sequence < before)
        result = await self.session.execute(
            stmt.order_by(StreamEventORM.sequence.desc()).limit(limit)
        )
        return [to_recorded(row) for row in result.scalars().all()]

    async def last_received_at(self, stream_id: UUID) -> datetime | None:
        await self._require_stream(stream_id)
        result = await self.session.execute(
            select(func.max(StreamEventORM.received_at)).where(
                StreamEventORM.stream_id == stream_id, self._in_workspace()
            )
        )
        return result.scalar_one()

    async def last_received_by_stream(self, stream_ids: list[UUID]) -> dict[UUID, datetime]:
        """Last event time of each of these streams that belongs to this workspace."""
        if not stream_ids:
            return {}
        rows = await self.session.execute(
            select(StreamEventORM.stream_id, func.max(StreamEventORM.received_at))
            .where(StreamEventORM.stream_id.in_(stream_ids), self._in_workspace())
            .group_by(StreamEventORM.stream_id)
        )
        return dict(rows.tuples().all())

    async def _require_stream(self, stream_id: UUID) -> None:
        found = await self.session.execute(
            select(StreamORM.id).where(
                StreamORM.id == stream_id, StreamORM.workspace_id == self.user_context.workspace_id
            )
        )
        if found.one_or_none() is None:
            raise StreamNotFoundError(stream_id)
