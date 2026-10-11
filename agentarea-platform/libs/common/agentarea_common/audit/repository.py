"""Audit event repository — append-only, workspace-scoped reads."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import literal, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AuditEventORM


class UnknownAuditCursorError(LookupError):
    """The cursor names no audit event of the workspace being paged."""


class AuditRepository:
    """Repository for audit events. Insert-only writes, filtered reads."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def insert(self, event: AuditEventORM) -> AuditEventORM:
        """Insert a new audit event. Never updates existing rows."""
        self._session.add(event)
        await self._session.flush()
        return event

    async def insert_once(self, event: AuditEventORM) -> bool:
        """Insert an event keyed by its preset ``id``; a repeat of that id is a no-op.

        For writers that are retried as a whole (Temporal activities): the same
        source event always maps to the same id, so a retry cannot double the
        trail. Returns whether this call wrote the row.
        """
        values = {
            column.key: value
            for column in AuditEventORM.__table__.columns
            if (value := getattr(event, column.key)) is not None
        }
        stmt = (
            pg_insert(AuditEventORM)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[AuditEventORM.id])
            .returning(AuditEventORM.id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def query(
        self,
        workspace_id: str,
        *,
        action: str | None = None,
        actor_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        cursor: UUID | None = None,
        limit: int = 50,
    ) -> list[AuditEventORM]:
        """Query audit events with workspace scoping and filtering, newest first.

        ``cursor`` is the id of the last event of the previous page. One that
        is not an event of this workspace raises ``UnknownAuditCursorError``
        rather than silently starting over at the first page.
        """
        stmt = (
            select(AuditEventORM)
            .where(AuditEventORM.workspace_id == workspace_id)
            # The id breaks ties, so events sharing a timestamp are neither
            # skipped nor repeated across a page boundary.
            .order_by(AuditEventORM.created_at.desc(), AuditEventORM.id.desc())
            .limit(min(limit, 100))
        )

        if action:
            stmt = stmt.where(AuditEventORM.action == action)
        if actor_id:
            stmt = stmt.where(AuditEventORM.actor_id == actor_id)
        if resource_type:
            stmt = stmt.where(AuditEventORM.resource_type == resource_type)
        if resource_id:
            stmt = stmt.where(AuditEventORM.resource_id == str(resource_id))
        if since:
            stmt = stmt.where(AuditEventORM.created_at >= since)
        if until:
            stmt = stmt.where(AuditEventORM.created_at <= until)
        if cursor:
            cursor_event = await self._session.get(AuditEventORM, cursor)
            if cursor_event is None or cursor_event.workspace_id != workspace_id:
                raise UnknownAuditCursorError(f"Unknown audit cursor {cursor}")
            stmt = stmt.where(
                tuple_(AuditEventORM.created_at, AuditEventORM.id)
                < tuple_(
                    literal(cursor_event.created_at, AuditEventORM.created_at.type),
                    literal(cursor_event.id, AuditEventORM.id.type),
                )
            )

        result = await self._session.execute(stmt)
        return list(result.scalars().all())
