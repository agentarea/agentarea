"""Append to and read from a stream's journal. append() never commits; the caller does."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.events.ports import IntegrationEvent
from sqlalchemy import ColumnElement, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.errors import PayloadTooLargeError, StreamNotFoundError, StreamQuotaExceededError
from ..domain.keys import MAX_EVENT_BYTES, encoded_size, event_id_for
from ..domain.models import AppendResult, JournaledEvent
from .orm import StreamEventKeyORM, StreamEventORM, StreamORM


def _now() -> datetime:
    return datetime.now(UTC)


def to_journaled(row: StreamEventORM) -> JournaledEvent:
    return JournaledEvent(
        id=row.event_id,
        type=row.kind,
        source=row.source,
        time=row.occurred_at,
        subject=row.subject,
        correlation_id=row.correlation_id,
        causation_id=row.causation_id,
        data=row.data,
        stream_id=row.stream_id,
        sequence=row.sequence,
        event_key=row.event_key,
        received_at=row.received_at,
        depth=row.depth,
    )


class StreamJournal:
    def __init__(
        self, session: AsyncSession, user_context: UserContext, settings: EventStreamSettings
    ):
        self.session = session
        self.user_context = user_context
        self.settings = settings

    async def append(
        self,
        stream_id: UUID,
        event: IntegrationEvent,
        *,
        event_key: str,
        source_id: UUID | None = None,
        depth: int = 0,
    ) -> AppendResult:
        if not event_key.strip():
            raise ValueError("event_key is required: name what distinguishes this event")
        size = encoded_size(event.data)
        if size > MAX_EVENT_BYTES:
            raise PayloadTooLargeError(size)
        await self._require_stream(stream_id, lock=True)
        workspace_id = self.user_context.workspace_id
        received_at = _now()
        await self._enforce_quota(workspace_id, received_at)
        sequence = (
            await self.session.execute(text("SELECT nextval('stream_events_sequence_seq')"))
        ).scalar_one()
        claimed = await self.session.execute(
            pg_insert(StreamEventKeyORM)
            .values(
                stream_id=stream_id,
                event_key=event_key,
                sequence=sequence,
                received_at=received_at,
            )
            .on_conflict_do_nothing(index_elements=["stream_id", "event_key"])
            .returning(StreamEventKeyORM.sequence)
        )
        if claimed.scalar_one_or_none() is None:
            existing = await self.session.execute(
                select(StreamEventKeyORM.sequence).where(
                    StreamEventKeyORM.stream_id == stream_id,
                    StreamEventKeyORM.event_key == event_key,
                )
            )
            return AppendResult(sequence=existing.scalar_one(), appended=False)
        await self.session.execute(
            pg_insert(StreamEventORM).values(
                sequence=sequence,
                received_at=received_at,
                stream_id=stream_id,
                event_id=event_id_for(stream_id, event_key),
                event_key=event_key,
                kind=event.type,
                source=event.source,
                subject=event.subject,
                occurred_at=event.time,
                correlation_id=event.correlation_id,
                causation_id=event.causation_id,
                source_id=source_id,
                depth=depth,
                data=event.data,
                workspace_id=workspace_id,
                created_by=self.user_context.user_id,
            )
        )
        return AppendResult(sequence=sequence, appended=True)

    async def _require_stream(self, stream_id: UUID, *, lock: bool) -> None:
        """Raise unless the stream is this workspace's; ``lock`` orders appends to it (D4)."""
        stmt = select(StreamORM.id).where(
            StreamORM.id == stream_id, StreamORM.workspace_id == self.user_context.workspace_id
        )
        if lock:
            stmt = stmt.with_for_update()
        if (await self.session.execute(stmt)).one_or_none() is None:
            raise StreamNotFoundError(stream_id)

    def _in_workspace(self) -> ColumnElement[bool]:
        return StreamEventORM.workspace_id == self.user_context.workspace_id

    async def _enforce_quota(self, workspace_id: str, now: datetime) -> None:
        recent = await self.session.execute(
            select(func.count())
            .select_from(StreamEventORM)
            .where(
                StreamEventORM.workspace_id == workspace_id,
                StreamEventORM.received_at > now - timedelta(minutes=1),
            )
        )
        if recent.scalar_one() >= self.settings.WRITE_QUOTA:
            raise StreamQuotaExceededError(workspace_id, self.settings.WRITE_QUOTA)

    async def read_after(self, stream_id: UUID, after: int, limit: int) -> list[JournaledEvent]:
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
        return [to_journaled(row) for row in result.scalars().all()]

    async def read_before(
        self, stream_id: UUID, before: int | None, limit: int
    ) -> list[JournaledEvent]:
        """Newest first; ``before=None`` starts at the newest event."""
        stmt = select(StreamEventORM).where(
            StreamEventORM.stream_id == stream_id, self._in_workspace()
        )
        if before is not None:
            stmt = stmt.where(StreamEventORM.sequence < before)
        result = await self.session.execute(
            stmt.order_by(StreamEventORM.sequence.desc()).limit(limit)
        )
        return [to_journaled(row) for row in result.scalars().all()]

    async def get(self, stream_id: UUID, sequence: int) -> JournaledEvent | None:
        result = await self.session.execute(
            select(StreamEventORM).where(
                StreamEventORM.stream_id == stream_id,
                StreamEventORM.sequence == sequence,
                self._in_workspace(),
            )
        )
        row = result.scalar_one_or_none()
        return to_journaled(row) if row else None

    async def last_sequence(self, stream_id: UUID) -> int:
        await self._require_stream(stream_id, lock=False)
        result = await self.session.execute(
            select(func.max(StreamEventKeyORM.sequence)).where(
                StreamEventKeyORM.stream_id == stream_id
            )
        )
        last = result.scalar_one()
        # Sequence 0 is "before the first event", the cursor of an empty stream.
        return 0 if last is None else last
