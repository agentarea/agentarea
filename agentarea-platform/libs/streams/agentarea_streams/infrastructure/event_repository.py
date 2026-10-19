"""The events read model: what the bus carried, by stream. Never commits; the caller does.

Written by the ``events-view`` group, read by the events page and agents.
Nothing reads it to decide what to fire.
"""

import logging
from datetime import datetime
from uuid import UUID

from agentarea_common.auth.context import UserContext
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.errors import StreamNotFoundError
from ..domain.models import Attachment, RecordedEvent, StreamEvent
from .orm import StreamEventORM, StreamORM

logger = logging.getLogger(__name__)

_FOREIGN_KEY_VIOLATION = "23503"


def to_recorded(row: StreamEventORM) -> RecordedEvent:
    return RecordedEvent(
        id=row.event_id,
        type=row.kind,
        source=row.source,
        time=row.occurred_at,
        subject=row.subject,
        correlation_id=row.correlation_id,
        causation_id=row.causation_id,
        data=row.data,
        stream_id=row.stream_id,
        workspace_id=row.workspace_id,
        created_by=row.created_by,
        sequence=row.sequence,
        event_key=row.event_key,
        received_at=row.received_at,
        depth=row.depth,
        source_id=row.source_id,
        source_type=row.source_type,
        session_key=row.session_key,
        sender=row.sender,
        attachments=[Attachment.model_validate(a) for a in row.attachments],
    )


class StreamEventRepository:
    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.user_context = user_context

    def _in_workspace(self) -> ColumnElement[bool]:
        return StreamEventORM.workspace_id == self.user_context.workspace_id

    async def record(self, event: StreamEvent) -> bool:
        """Insert the event once; False for a repeat or a stream deleted meanwhile."""
        if event.workspace_id != self.user_context.workspace_id:
            raise ValueError(
                f"event {event.id} belongs to workspace {event.workspace_id}, "
                + f"not {self.user_context.workspace_id}"
            )
        seen = await self.session.execute(
            select(StreamEventORM.sequence)
            .where(StreamEventORM.event_id == event.id, self._in_workspace())
            .limit(1)
        )
        if seen.first() is not None:
            return False
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
                    )
                    .on_conflict_do_nothing(index_elements=["event_id", "received_at"])
                    .returning(StreamEventORM.sequence)
                )
                return inserted.scalar_one_or_none() is not None
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) != _FOREIGN_KEY_VIOLATION:
                raise
            logger.info(
                "Event %s not recorded: stream %s no longer exists", event.id, event.stream_id
            )
            return False

    async def read_by_id(self, event_id: UUID) -> RecordedEvent | None:
        """The event with this id in this workspace, whichever stream holds it."""
        result = await self.session.execute(
            select(StreamEventORM)
            .where(StreamEventORM.event_id == event_id, self._in_workspace())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return to_recorded(row) if row is not None else None

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
