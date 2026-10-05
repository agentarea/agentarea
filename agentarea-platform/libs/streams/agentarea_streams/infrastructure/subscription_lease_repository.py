"""The dispatcher's hold on subscriptions: claim, renew, move the cursor, release. Never commits.

Every write is guarded by ``lease_owner``. ``claim_due`` and ``release_all``
span every workspace and run inside the caller's ``unscoped``; every other
method filters by the subscription's own workspace explicitly.
"""

from datetime import datetime
from typing import Any, cast

from sqlalchemy import exists, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import SubscriptionStatus
from ..domain.models import SubscriptionView
from .orm import StreamEventKeyORM, StreamSubscriptionORM


class SubscriptionLeaseRepository:
    def __init__(self, session: AsyncSession, owner: str):
        self.session = session
        self.owner = owner

    def _held(self, view: SubscriptionView):
        return (
            StreamSubscriptionORM.id == view.id,
            StreamSubscriptionORM.workspace_id == view.workspace_id,
            StreamSubscriptionORM.lease_owner == self.owner,
        )

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
        rows = await self.session.execute(
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
        await self.session.execute(
            update(StreamSubscriptionORM)
            .where(StreamSubscriptionORM.lease_owner == self.owner)
            .values(leased_until=None, lease_owner=None)
        )

    async def renew(self, view: SubscriptionView, *, now: datetime, until: datetime) -> bool:
        """Extend a lease still ours and unexpired; False when it lapsed."""
        renewed = await self.session.execute(
            update(StreamSubscriptionORM)
            .where(*self._held(view), StreamSubscriptionORM.leased_until > now)
            .values(leased_until=until)
        )
        return cast(CursorResult[Any], renewed).rowcount == 1

    async def cursor(self, view: SubscriptionView) -> int:
        return (
            await self.session.execute(
                select(StreamSubscriptionORM.cursor_sequence).where(
                    StreamSubscriptionORM.id == view.id,
                    StreamSubscriptionORM.workspace_id == view.workspace_id,
                )
            )
        ).scalar_one()

    async def advance(
        self, view: SubscriptionView, sequence: int, *, now: datetime, until: datetime
    ) -> bool:
        """Move the cursor and clear the failure state; False when the lease is not ours."""
        moved = await self.session.execute(
            update(StreamSubscriptionORM)
            .where(*self._held(view))
            .values(
                cursor_sequence=sequence,
                attempts=0,
                next_attempt_at=None,
                last_error=None,
                leased_until=until,
                updated_at=now,
            )
        )
        return cast(CursorResult[Any], moved).rowcount != 0

    async def lock_if_held(self, view: SubscriptionView) -> StreamSubscriptionORM | None:
        """The subscription row, locked until commit, while the lease is still ours."""
        return (
            await self.session.execute(
                select(StreamSubscriptionORM)
                .where(*self._held(view))
                # Held until commit: a claimer skips the row instead of taking it
                # between this read and the caller's write.
                .with_for_update()
            )
        ).scalar_one_or_none()

    async def release(self, view: SubscriptionView) -> None:
        await self.session.execute(
            update(StreamSubscriptionORM)
            .where(*self._held(view))
            .values(leased_until=None, lease_owner=None)
        )
