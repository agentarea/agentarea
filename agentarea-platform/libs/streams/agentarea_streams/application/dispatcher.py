"""Fan-out: every subscription of a stream gets every event that passes its filter.

Subscriptions are leased with FOR UPDATE SKIP LOCKED and a lease column, not a
held row lock: trigger handlers commit inside their own services, which would
release a row lock halfway. Each event's outcome and the cursor move commit in
one transaction, guarded by the lease, which every committed event renews.

Claiming spans every workspace; everything after the claim runs scoped to the
subscription's own workspace and filters by it explicitly.
"""

import asyncio
import logging
import os
import socket
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import unscoped, workspace_scope
from agentarea_common.config.streams import EventStreamSettings
from sqlalchemy import exists, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..domain.enums import SubscriptionKind, SubscriptionStatus, Verdict
from ..domain.errors import LeaseLostError
from ..domain.filters import EventFilter
from ..domain.models import HandlerResult, JournaledEvent, SubscriptionView
from ..domain.ports import StreamWaker, SubscriptionHandler
from ..infrastructure.journal import StreamJournal
from ..infrastructure.orm import StreamEventKeyORM, StreamSubscriptionORM, SubscriptionOutcomeORM

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(2 ** min(attempts - 1, 30), 300))


def _view(row: StreamSubscriptionORM) -> SubscriptionView:
    return SubscriptionView(
        id=row.id,
        workspace_id=row.workspace_id,
        created_by=row.created_by,
        stream_id=row.stream_id,
        kind=SubscriptionKind(row.kind),
        trigger_id=row.trigger_id,
        filter=EventFilter.model_validate(row.filter),
        output_stream_ids=[UUID(s) for s in row.output_stream_ids],
    )


class StreamDispatcher:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        settings: EventStreamSettings,
        handlers: Mapping[SubscriptionKind, SubscriptionHandler],
        waker: StreamWaker,
        owner: str | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ):
        missing = sorted(kind.value for kind in SubscriptionKind if kind not in handlers)
        if missing:
            raise ValueError(f"StreamDispatcher needs a handler for {', '.join(missing)}")
        self._session_factory = session_factory
        self._settings = settings
        self._handlers = dict(handlers)
        self._waker = waker
        self._owner = owner or f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
        self._clock = clock
        self._wakeup = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def notify(self, stream_id: UUID) -> None:
        self._wakeup.set()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="stream-dispatcher")
        logger.info("StreamDispatcher started as %s", self._owner)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        with unscoped("a stopping dispatcher hands back its leases in every workspace"):
            async with self._session_factory() as session:
                await session.execute(
                    update(StreamSubscriptionORM)
                    .where(StreamSubscriptionORM.lease_owner == self._owner)
                    .values(leased_until=None, lease_owner=None)
                )
                await session.commit()

    async def _loop(self) -> None:
        while True:
            try:
                handled = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("StreamDispatcher pass failed; retrying after the poll interval")
                handled = 0
            if handled:
                continue
            try:
                await asyncio.wait_for(
                    self._wakeup.wait(), timeout=self._settings.DISPATCH_EVERY.total_seconds()
                )
            except TimeoutError:
                pass
            self._wakeup.clear()

    async def run_once(self) -> int:
        """Serve every due subscription once; returns events handled or filtered out."""
        handled = 0
        for view in await self._claim():
            try:
                handled += await self._drain(view)
            except Exception:
                # One subscription's failure must not hold back the others claimed with
                # it; its lease expires and a later pass serves it again.
                logger.exception(
                    "Subscription %s could not be served; its lease lapses and it is retried",
                    view.id,
                )
        return handled

    async def _claim(self) -> list[SubscriptionView]:
        now = self._clock()
        has_new = exists(
            select(StreamEventKeyORM.stream_id).where(
                StreamEventKeyORM.stream_id == StreamSubscriptionORM.stream_id,
                StreamEventKeyORM.sequence > StreamSubscriptionORM.cursor_sequence,
            )
        )
        with unscoped("the dispatcher serves the subscriptions of every workspace"):
            async with self._session_factory() as session:
                rows = await session.execute(
                    select(StreamSubscriptionORM)
                    .where(
                        StreamSubscriptionORM.status == SubscriptionStatus.ACTIVE.value,
                        # A kind this worker has no handler for (a newer release's) is
                        # left for a worker that has one.
                        StreamSubscriptionORM.kind.in_([kind.value for kind in self._handlers]),
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
                    .limit(self._settings.DISPATCH_BATCH)
                    .with_for_update(skip_locked=True)
                )
                views: list[SubscriptionView] = []
                for row in rows.scalars().all():
                    try:
                        views.append(_view(row))
                    except Exception as error:
                        # One unreadable row fails alone; left active it would head
                        # every batch and stall dispatch for every workspace.
                        logger.error(
                            "Subscription %s is unreadable and is marked failed",
                            row.id,
                            exc_info=True,
                        )
                        row.status = SubscriptionStatus.FAILED.value
                        row.last_error = f"unreadable subscription: {error}"[:2000]
                        continue
                    row.leased_until = now + self._settings.LEASE
                    row.lease_owner = self._owner
                await session.commit()
                return views

    async def _drain(self, view: SubscriptionView) -> int:
        handler = self._handlers[view.kind]
        context = UserContext(user_id=view.created_by, workspace_id=view.workspace_id)
        handled = 0
        with workspace_scope(view.workspace_id):
            if not await self._renew(view):
                logger.info(
                    "Subscription %s lost its lease while queued in this pass; skipping it",
                    view.id,
                )
                return handled
            async with self._session_factory() as session:
                cursor = (
                    await session.execute(
                        select(StreamSubscriptionORM.cursor_sequence).where(
                            StreamSubscriptionORM.id == view.id,
                            StreamSubscriptionORM.workspace_id == view.workspace_id,
                        )
                    )
                ).scalar_one()
                events = await StreamJournal(session, context, self._settings).read_after(
                    view.stream_id, cursor, self._settings.DISPATCH_BATCH
                )
            for event in events:
                try:
                    await self._deliver(view, handler, event)
                    handled += 1
                except LeaseLostError:
                    logger.warning(
                        "Subscription %s was taken over before event %s committed",
                        view.id,
                        event.sequence,
                    )
                    return handled
                except Exception as error:
                    await self._retry_later(view, event, error)
                    return handled
            await self._release(view)
        return handled

    async def _deliver(
        self, view: SubscriptionView, handler: SubscriptionHandler, event: JournaledEvent
    ) -> None:
        async with self._session_factory() as session:
            result: HandlerResult | None = None
            if view.filter.matches(event.type, event.data):
                result = await handler.handle(view, event, session)
                await self._record(session, view, event, result)
            await self._advance(session, view, event.sequence)
            await session.commit()
        if result and result.derived_sequences:
            for output in view.output_stream_ids:
                try:
                    await self._waker.wake(output)
                except Exception:
                    # The forwarded events are committed; the poll delivers them. The
                    # event must not be charged a failed attempt for a lost wake.
                    logger.warning(
                        "Wake for stream %s failed; the dispatcher's poll picks it up",
                        output,
                        exc_info=True,
                    )

    async def _renew(self, view: SubscriptionView) -> bool:
        """Extend a lease still ours and unexpired; False when it lapsed while queued."""
        now = self._clock()
        async with self._session_factory() as session:
            renewed = await session.execute(
                update(StreamSubscriptionORM)
                .where(
                    StreamSubscriptionORM.id == view.id,
                    StreamSubscriptionORM.workspace_id == view.workspace_id,
                    StreamSubscriptionORM.lease_owner == self._owner,
                    StreamSubscriptionORM.leased_until > now,
                )
                .values(leased_until=now + self._settings.LEASE)
            )
            await session.commit()
        return cast(CursorResult[Any], renewed).rowcount == 1

    async def _record(
        self,
        session: AsyncSession,
        view: SubscriptionView,
        event: JournaledEvent,
        result: HandlerResult,
    ) -> None:
        now = self._clock()
        await session.execute(
            pg_insert(SubscriptionOutcomeORM)
            .values(
                id=uuid4(),
                subscription_id=view.id,
                stream_id=view.stream_id,
                event_sequence=event.sequence,
                verdict=result.verdict.value,
                reason=result.reason,
                score=result.score,
                task_id=result.task_id,
                derived_sequences=result.derived_sequences,
                workspace_id=view.workspace_id,
                created_by=view.created_by,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_subscription_outcomes_event")
        )

    async def _advance(self, session: AsyncSession, view: SubscriptionView, sequence: int) -> None:
        now = self._clock()
        moved = await session.execute(
            update(StreamSubscriptionORM)
            .where(
                StreamSubscriptionORM.id == view.id,
                StreamSubscriptionORM.workspace_id == view.workspace_id,
                StreamSubscriptionORM.lease_owner == self._owner,
            )
            .values(
                cursor_sequence=sequence,
                attempts=0,
                next_attempt_at=None,
                last_error=None,
                leased_until=now + self._settings.LEASE,
                updated_at=now,
            )
        )
        if cast(CursorResult[Any], moved).rowcount == 0:
            await session.rollback()
            raise LeaseLostError(f"subscription {view.id} is no longer leased by {self._owner}")

    async def _retry_later(
        self, view: SubscriptionView, event: JournaledEvent, error: Exception
    ) -> None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(StreamSubscriptionORM)
                    .where(
                        StreamSubscriptionORM.id == view.id,
                        StreamSubscriptionORM.workspace_id == view.workspace_id,
                        StreamSubscriptionORM.lease_owner == self._owner,
                    )
                    # Held until commit: a claimer skips the row instead of taking it
                    # between this read and the write below.
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is None:
                logger.warning(
                    "Subscription %s failed on event %s after losing its lease; the holder retries",
                    view.id,
                    event.sequence,
                    exc_info=error,
                )
                return
            attempts = row.attempts + 1
            if attempts >= self._settings.MAX_ATTEMPTS:
                logger.error(
                    "Subscription %s gave up on event %s after %d attempts",
                    view.id,
                    event.sequence,
                    attempts,
                    exc_info=error,
                )
                await self._record(
                    session,
                    view,
                    event,
                    HandlerResult(verdict=Verdict.ERROR, reason=f"gave up: {error}"),
                )
                await self._advance(session, view, event.sequence)
            else:
                logger.warning(
                    "Subscription %s failed on event %s (attempt %d); retrying in %s",
                    view.id,
                    event.sequence,
                    attempts,
                    backoff(attempts),
                    exc_info=error,
                )
                row.attempts = attempts
                row.next_attempt_at = self._clock() + backoff(attempts)
                row.last_error = str(error)[:2000]
            row.leased_until = None
            row.lease_owner = None
            await session.commit()

    async def _release(self, view: SubscriptionView) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(StreamSubscriptionORM)
                .where(
                    StreamSubscriptionORM.id == view.id,
                    StreamSubscriptionORM.workspace_id == view.workspace_id,
                    StreamSubscriptionORM.lease_owner == self._owner,
                )
                .values(leased_until=None, lease_owner=None)
            )
            await session.commit()
