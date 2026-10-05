"""The two subscription lease operations that span every workspace. Never commits.

The dispatcher claims due subscriptions of every workspace in one scan and,
when it stops, hands back every lease it holds wherever it is. Both run inside
the dispatcher's ``unscoped``, which also covers the commit that flushes the
claimed rows. Everything done to one claimed subscription goes through the
workspace-scoped ``StreamSubscriptionRepository`` instead.
"""

from datetime import datetime

from sqlalchemy import exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import SubscriptionStatus
from .orm import StreamEventKeyORM, StreamSubscriptionORM


class CrossWorkspaceLeases:
    def __init__(self, session: AsyncSession, owner: str):
        self._session = session
        self._owner = owner

    async def claim_due(
        self, *, now: datetime, kinds: list[str], limit: int
    ) -> list[StreamSubscriptionORM]:
        """Active, due, unleased subscriptions with unread events, locked SKIP LOCKED."""
        has_new = exists(
            select(StreamEventKeyORM.stream_id).where(
                StreamEventKeyORM.stream_id == StreamSubscriptionORM.stream_id,
                StreamEventKeyORM.sequence > StreamSubscriptionORM.cursor_sequence,
            )
        )
        rows = await self._session.execute(
            select(StreamSubscriptionORM)
            .where(
                StreamSubscriptionORM.status == SubscriptionStatus.ACTIVE.value,
                StreamSubscriptionORM.kind.in_(kinds),
                or_(
                    StreamSubscriptionORM.next_attempt_at.is_(None),
                    StreamSubscriptionORM.next_attempt_at <= now,
                ),
                or_(
                    StreamSubscriptionORM.leased_until.is_(None),
                    StreamSubscriptionORM.leased_until < now,
                ),
                has_new,
            )
            .order_by(StreamSubscriptionORM.updated_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(rows.scalars().all())

    async def release_all(self) -> None:
        await self._session.execute(
            update(StreamSubscriptionORM)
            .where(StreamSubscriptionORM.lease_owner == self._owner)
            .values(leased_until=None, lease_owner=None)
        )
