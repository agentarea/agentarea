"""Repository for the transactional event outbox.

Two distinct access patterns share one repository:

* ``add`` runs inside a service's unit of work — it inserts a row on the
  caller's session and does NOT commit, so the row commits atomically with the
  aggregate change (or rolls back with it).
* ``fetch_unpublished`` / ``mark_*`` are used by the relay, which reads across
  ALL workspaces (it is infrastructure, not a workspace-scoped request) and uses
  ``SELECT ... FOR UPDATE SKIP LOCKED`` so multiple relay instances never grab
  the same row.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from agentarea_common.auth.context import UserContext
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .base_events import EventEnvelope
from .outbox_orm import EventOutbox

logger = logging.getLogger(__name__)


class OutboxRepository:
    """Persistence for outbox rows on a caller-owned session."""

    def __init__(self, session: AsyncSession, user_context: UserContext) -> None:
        self.session = session
        self.user_context = user_context

    async def add(
        self,
        event_envelope: EventEnvelope,
        *,
        aggregate_id: str,
        aggregate_type: str,
    ) -> EventOutbox:
        """Enqueue an event row on the caller's session WITHOUT committing.

        The service's unit of work owns the commit, so the outbox row lands in
        the same transaction as the aggregate change. If enqueueing fails the
        exception propagates — the whole operation must fail (never swallow).
        """
        row = EventOutbox(
            event_id=event_envelope.event_id,
            event_type=event_envelope.event_type,
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            payload=event_envelope.as_json_dict(),
            workspace_id=self.user_context.workspace_id,
            created_by=self.user_context.user_id,
        )
        self.session.add(row)
        # Flush so uniqueness / NOT NULL violations surface inside this UoW
        # rather than silently at an unrelated commit later.
        await self.session.flush()
        return row

    async def fetch_unpublished(self, limit: int = 100) -> list[EventOutbox]:
        """Fetch and lock unpublished rows for the relay.

        ``FOR UPDATE SKIP LOCKED`` lets concurrent relay loops divide the work
        with no coordination. On SQLite (tests) ``skip_locked`` is a no-op.
        """
        stmt = (
            select(EventOutbox)
            .where(EventOutbox.published_at.is_(None))
            .order_by(EventOutbox.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def mark_published(self, outbox_id: UUID) -> None:
        await self.session.execute(
            update(EventOutbox)
            .where(EventOutbox.id == outbox_id)
            .values(published_at=datetime.now(UTC).replace(tzinfo=None))
        )

    async def mark_failed(self, outbox_id: UUID, error: str) -> None:
        await self.session.execute(
            update(EventOutbox)
            .where(EventOutbox.id == outbox_id)
            .values(attempts=EventOutbox.attempts + 1, last_error=error)
        )
