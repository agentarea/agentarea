"""The ``router`` group: every bus event to every matching subscription of its stream.

Subscription configuration is cached per stream and dropped when a domain event
says a stream's subscriptions changed; it also expires. It serves only events
received before it was read: a newer event reads the subscriptions again, so a
subscription created a moment before an event is never missed while its change
notice is on its way. Before acting on a match the
router re-reads the subscription, so a stale cache never fires a deleted or
paused one.

Each reaction is recorded (``ReactionLog``) before the message is acknowledged.
A redelivered event finds the reactions already recorded and runs only the
rest. A failure leaves the message unacknowledged: the broker redelivers it, and
past ``MAX_ATTEMPTS`` the adapter calls ``give_up``, which records the remaining
reactions as ``error`` before the message goes to ``streams.events.router.dlq``.
A replay of the dead letter runs those reactions again: a given-up reaction does
not count as recorded.
"""

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.events.ports import IntegrationEvent, UnprocessableEventError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..domain.enums import GAVE_UP_REASON, SubscriptionKind, SubscriptionStatus, Verdict
from ..domain.filters import EventFilter
from ..domain.models import HandlerResult, StreamEvent, SubscriptionView
from ..domain.ports import ReactionLog, SubscriptionHandler
from ..infrastructure.orm import StreamSubscriptionORM
from ..infrastructure.repository import StreamSubscriptionRepository

logger = logging.getLogger(__name__)

DEFAULT_CACHE_TTL_S = 60.0


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ReactionsFailedError(RuntimeError):
    """Some subscriptions could not react; the event is redelivered for them."""


def _stream_event(message: IntegrationEvent) -> StreamEvent:
    try:
        return StreamEvent.from_bus(message)
    except Exception as error:
        raise UnprocessableEventError(f"not a stream event: {error}") from error


def subscription_view(row: StreamSubscriptionORM) -> SubscriptionView:
    return SubscriptionView(
        id=row.id,
        workspace_id=row.workspace_id,
        created_by=row.created_by,
        stream_id=row.stream_id,
        kind=SubscriptionKind(row.kind),
        trigger_id=row.trigger_id,
        filter=EventFilter.model_validate(row.filter),
        output_stream_ids=[UUID(str(s)) for s in row.output_stream_ids],
    )


@dataclass
class _Cached:
    views: list[SubscriptionView]
    loaded_at: float
    # When the subscriptions were read: they cover events received before it.
    read_at: datetime


class EventRouter:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        handlers: Mapping[SubscriptionKind, SubscriptionHandler],
        reactions: ReactionLog,
        cache_ttl_s: float = DEFAULT_CACHE_TTL_S,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = _utcnow,
    ):
        missing = sorted(kind.value for kind in SubscriptionKind if kind not in handlers)
        if missing:
            raise ValueError(f"EventRouter needs a handler for {', '.join(missing)}")
        self._session_factory = session_factory
        self._handlers = dict(handlers)
        self._reactions = reactions
        self._cache_ttl_s = cache_ttl_s
        self._clock = clock
        self._wall_clock = wall_clock
        self._cache: dict[UUID, _Cached] = {}

    def invalidate(self, stream_id: UUID | None) -> None:
        """Forget one stream's subscriptions, or every stream's with ``None``."""
        if stream_id is None:
            self._cache.clear()
        else:
            self._cache.pop(stream_id, None)

    async def handle(self, message: IntegrationEvent) -> None:
        event = _stream_event(message)
        with workspace_scope(event.workspace_id):
            pending = await self._pending(event)
            failed: list[UUID] = []
            for view in pending:
                try:
                    await self._react(view, event)
                except Exception:
                    # One subscription's failure must not hold back the others;
                    # the redelivery runs only what is not recorded yet.
                    logger.warning(
                        "Subscription %s failed on event %s of stream %s; it is retried",
                        view.id,
                        event.id,
                        event.stream_id,
                        exc_info=True,
                    )
                    failed.append(view.id)
            if failed:
                raise ReactionsFailedError(
                    f"event {event.id}: subscriptions {', '.join(map(str, failed))} failed"
                )

    async def give_up(self, message: IntegrationEvent) -> None:
        """Record every reaction still missing as ``error``; the event is dead-lettered."""
        event = _stream_event(message)
        with workspace_scope(event.workspace_id):
            for view in await self._pending(event):
                async with self._session_factory() as session:
                    current = await self._recheck(session, view)
                    if current is None:
                        continue
                    await self._reactions.record(
                        session,
                        current,
                        event,
                        HandlerResult(verdict=Verdict.ERROR, reason=GAVE_UP_REASON),
                    )
                    await session.commit()

    async def _pending(self, event: StreamEvent) -> list[SubscriptionView]:
        matching = [
            view
            for view in await self._subscriptions(event)
            if view.filter.matches(event.type, event.data)
        ]
        if not matching:
            return []
        async with self._session_factory() as session:
            done = await self._reactions.recorded(session, event)
        return [view for view in matching if view.id not in done]

    async def _react(self, view: SubscriptionView, event: StreamEvent) -> None:
        async with self._session_factory() as session:
            current = await self._recheck(session, view)
            if current is None:
                logger.info(
                    "Subscription %s is gone or paused; event %s is not delivered to it",
                    view.id,
                    event.id,
                )
                return
            await self._reactions.forget_given_up(session, current, event)
            result = await self._handlers[current.kind].handle(current, event, session)
            try:
                await self._reactions.record(session, current, event, result)
                await session.commit()
            except IntegrityError:
                await session.rollback()
                if await self._recheck(session, current) is not None:
                    raise
                # Deleted while it reacted: there is no subscription to record against.
                logger.info(
                    "Subscription %s was deleted while it reacted to event %s; not recorded",
                    view.id,
                    event.id,
                )

    async def _recheck(
        self, session: AsyncSession, view: SubscriptionView
    ) -> SubscriptionView | None:
        row = await StreamSubscriptionRepository(
            session, UserContext(user_id=view.created_by, workspace_id=view.workspace_id)
        ).get_active(view.id)
        return subscription_view(row) if row is not None else None

    async def _subscriptions(self, event: StreamEvent) -> list[SubscriptionView]:
        cached = self._cache.get(event.stream_id)
        now = self._clock()
        # A subscription created after the cache was read may already be due this
        # event; the change notice arrives seconds later. Only an event received
        # before the read is served from it.
        if (
            cached is not None
            and now - cached.loaded_at < self._cache_ttl_s
            and event.received_at <= cached.read_at
        ):
            return cached.views
        read_at = self._wall_clock()
        async with self._session_factory() as session:
            rows = await StreamSubscriptionRepository(
                session, UserContext(user_id=event.created_by, workspace_id=event.workspace_id)
            ).list_for_stream(event.stream_id)
        views: list[SubscriptionView] = []
        for row in rows:
            if row.status != SubscriptionStatus.ACTIVE.value:
                continue
            try:
                views.append(subscription_view(row))
            except Exception:
                logger.error(
                    "Subscription %s is unreadable; the router skips it", row.id, exc_info=True
                )
        self._cache[event.stream_id] = _Cached(views=views, loaded_at=now, read_at=read_at)
        return views
