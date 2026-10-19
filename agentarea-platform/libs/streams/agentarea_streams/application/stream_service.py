"""Streams, their sources and subscriptions, as one workspace sees them. Never commits."""

import secrets
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from agentarea_common.base import RepositoryFactory
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.events.base_events import DomainEvent
from agentarea_common.events.outbox_publisher import OutboxPublisher

from ..domain.enums import SourceKind, StreamKind, SubscriptionKind
from ..domain.errors import (
    ForwardLoopError,
    NotAForwardError,
    StreamEventNotFoundError,
    StreamInUseError,
    StreamNotFoundError,
    StreamSourceNotFoundError,
    SubscriptionNotFoundError,
    TriggerSubscriptionNotFoundError,
)
from ..domain.events import SUBSCRIPTIONS_CHANGED
from ..domain.filters import EventFilter
from ..domain.models import RecordedEvent, TriggerBinding
from ..infrastructure.event_repository import StreamEventRepository
from ..infrastructure.orm import StreamORM, StreamSourceORM, StreamSubscriptionORM
from ..infrastructure.repository import (
    StreamRepository,
    StreamSourceRepository,
    StreamSubscriptionRepository,
)


class StreamService:
    def __init__(self, repository_factory: RepositoryFactory, settings: EventStreamSettings):
        self.repository_factory = repository_factory
        self.settings = settings

    @property
    def _session(self):
        return self.repository_factory.session

    def _streams(self) -> StreamRepository:
        return self.repository_factory.create_repository(StreamRepository)

    def _sources(self) -> StreamSourceRepository:
        return self.repository_factory.create_repository(StreamSourceRepository)

    def _subscriptions(self) -> StreamSubscriptionRepository:
        return self.repository_factory.create_repository(StreamSubscriptionRepository)

    def _events(self) -> StreamEventRepository:
        return StreamEventRepository(self._session, self.repository_factory.user_context)

    async def _subscriptions_changed(self, stream_id: UUID) -> None:
        """Tell the router, after commit, to reload this stream's subscriptions."""
        await OutboxPublisher(self._session, self.repository_factory.user_context).publish(
            DomainEvent(
                event_type=SUBSCRIPTIONS_CHANGED,
                stream_id=str(stream_id),
                aggregate_id=str(stream_id),
                aggregate_type="stream",
            )
        )

    async def create_stream(self, *, name: str, description: str) -> StreamORM:
        return await self._streams().add_stream(
            name=name, description=description, kind=StreamKind.CUSTOM
        )

    async def get_stream(self, stream_id: UUID) -> StreamORM:
        stream = await self._streams().get_by_id(stream_id)
        if stream is None:
            raise StreamNotFoundError(stream_id)
        return stream

    async def find_stream(self, name_or_id: str) -> StreamORM:
        """A stream of this workspace by its id or, failing that, its name."""
        try:
            stream_id = UUID(name_or_id)
        except ValueError:
            stream_id = None
        stream = await self._streams().get_by_id(stream_id) if stream_id else None
        if stream is None:
            stream = await self._streams().get_by_name(name_or_id)
        if stream is None:
            raise StreamNotFoundError(name_or_id)
        return stream

    async def list_streams(
        self, *, limit: int, offset: int, ids: set[str] | None
    ) -> list[StreamORM]:
        return await self._streams().list_all(limit=limit, offset=offset, ids=ids)

    async def ensure_deletable(self, stream_id: UUID) -> None:
        """Raise unless the stream can go without stranding what depends on it.

        Refused while a trigger subscribes to it or a forward writes into it
        (``StreamInUseError``): the subscription would cascade away and leave its
        trigger active but deaf, and a forward's outputs are not a foreign key,
        so it would keep retrying a missing stream. The stream row stays locked
        until commit, so none is added meanwhile.
        """
        if await self._streams().lock_for_delete(stream_id) is None:
            raise StreamNotFoundError(stream_id)
        triggers = await self._subscriptions().trigger_ids_on_stream(stream_id)
        forwards = await self._subscriptions().forwards_into(stream_id)
        if triggers or forwards:
            raise StreamInUseError(stream_id, triggers, [(f.id, f.stream_id) for f in forwards])

    async def delete_stream(self, stream_id: UUID) -> None:
        """Refused while anything depends on the stream; see ``ensure_deletable``."""
        await self.ensure_deletable(stream_id)
        if not await self._streams().delete_in_workspace(stream_id):
            raise StreamNotFoundError(stream_id)
        await self._subscriptions_changed(stream_id)

    async def add_source(
        self,
        *,
        stream_id: UUID,
        kind: SourceKind,
        source_type: str,
        webhook_config: dict[str, Any],
        event_templates: dict[str, Any] | None,
    ) -> StreamSourceORM:
        """A webhook source gets its public webhook id; a poll source is fetched by Go."""
        await self.get_stream(stream_id)
        return await self._sources().add_source(
            source_id=uuid4(),
            stream_id=stream_id,
            kind=kind,
            source_type=source_type,
            webhook_id=secrets.token_urlsafe(16) if kind == SourceKind.WEBHOOK else None,
            webhook_config=webhook_config,
            event_templates=event_templates,
        )

    async def get_source(self, stream_id: UUID, source_id: UUID) -> StreamSourceORM:
        source = await self._sources().get_in_stream(stream_id, source_id)
        if source is None:
            raise StreamSourceNotFoundError(source_id)
        return source

    async def delete_source(self, stream_id: UUID, source_id: UUID) -> StreamSourceORM:
        source = await self.get_source(stream_id, source_id)
        if not await self._sources().delete_in_workspace(source.id):
            raise StreamSourceNotFoundError(source_id)
        return source

    async def subscribe_trigger(
        self, *, stream_id: UUID, trigger_id: UUID, event_filter: EventFilter
    ) -> StreamSubscriptionORM:
        await self.get_stream(stream_id)
        subscription = await self._subscriptions().add_subscription(
            stream_id=stream_id,
            kind=SubscriptionKind.TRIGGER,
            trigger_id=trigger_id,
            filter=event_filter,
            output_stream_ids=[],
        )
        await self._subscriptions_changed(stream_id)
        return subscription

    async def update_trigger_filter(self, trigger_id: UUID, event_filter: EventFilter) -> None:
        if not await self._subscriptions().update_filter_for_trigger(trigger_id, event_filter):
            raise TriggerSubscriptionNotFoundError(trigger_id)
        subscription = await self._subscriptions().get_for_trigger(trigger_id)
        if subscription is not None:
            await self._subscriptions_changed(subscription.stream_id)

    async def create_forward(
        self, *, stream_id: UUID, output_stream_ids: list[UUID], event_filter: EventFilter
    ) -> StreamSubscriptionORM:
        if not output_stream_ids:
            raise ForwardLoopError("A forward needs at least one output stream")
        if stream_id in output_stream_ids:
            raise ForwardLoopError("A forward may not write into its own input stream")
        output_stream_ids = list(dict.fromkeys(output_stream_ids))
        await self.get_stream(stream_id)
        # Locked, not just read: a stream deleted meanwhile would leave the forward
        # writing into nothing, since its outputs are not a foreign key.
        found = await self._streams().lock_existing(output_stream_ids)
        for output in output_stream_ids:
            if output not in found:
                raise StreamNotFoundError(output)
        forward = await self._subscriptions().add_subscription(
            stream_id=stream_id,
            kind=SubscriptionKind.FORWARD,
            trigger_id=None,
            filter=event_filter,
            output_stream_ids=output_stream_ids,
        )
        await self._subscriptions_changed(stream_id)
        return forward

    async def get_forward(self, stream_id: UUID, subscription_id: UUID) -> StreamSubscriptionORM:
        """A forward of the stream; a trigger's subscription is refused, it goes with its trigger."""
        subscription = await self._subscriptions().get_in_stream(stream_id, subscription_id)
        if subscription is None:
            raise SubscriptionNotFoundError(subscription_id)
        if subscription.kind != SubscriptionKind.FORWARD.value:
            raise NotAForwardError(subscription_id, subscription.trigger_id)
        return subscription

    async def existing_outputs(self, forward: StreamSubscriptionORM) -> list[UUID]:
        """The forward's outputs that still exist; older releases let an output be deleted."""
        outputs = [UUID(str(s)) for s in forward.output_stream_ids]
        found = await self._streams().lock_existing(outputs)
        return [o for o in outputs if o in found]

    async def delete_forward(self, stream_id: UUID, subscription_id: UUID) -> None:
        """Remove a forward; its reactions go with it, the events it copied stay."""
        forward = await self.get_forward(stream_id, subscription_id)
        if not await self._subscriptions().delete_in_workspace(forward.id):
            raise SubscriptionNotFoundError(subscription_id)
        await self._subscriptions_changed(stream_id)

    async def trigger_subscription(self, trigger_id: UUID) -> StreamSubscriptionORM | None:
        return await self._subscriptions().get_for_trigger(trigger_id)

    async def last_received_at(self, stream_id: UUID) -> datetime | None:
        await self.get_stream(stream_id)
        return await self._events().last_received_at(stream_id)

    async def trigger_bindings(self, trigger_ids: list[UUID]) -> dict[UUID, TriggerBinding]:
        """Stream, filter and last event of each trigger, in two queries."""
        if not trigger_ids:
            return {}
        subscriptions = await self._subscriptions().list_for_triggers(trigger_ids)
        last_by_stream = await self._events().last_received_by_stream(
            list({s.stream_id for s in subscriptions})
        )
        return {
            s.trigger_id: TriggerBinding(
                stream_id=s.stream_id,
                event_filter=s.filter,
                last_event_at=last_by_stream.get(s.stream_id),
            )
            for s in subscriptions
            if s.trigger_id is not None
        }

    async def list_sources(self, stream_id: UUID) -> list[StreamSourceORM]:
        return await self._sources().list_for_stream(stream_id)

    async def list_subscriptions(self, stream_id: UUID) -> list[StreamSubscriptionORM]:
        return await self._subscriptions().list_for_stream(stream_id)

    async def list_events(
        self, stream_id: UUID, *, after: int | None, before: int | None, limit: int
    ) -> list[RecordedEvent]:
        """Oldest first after ``after``; otherwise newest first before ``before``."""
        await self.get_stream(stream_id)
        if after is not None:
            return await self._events().read_after(stream_id, after, limit)
        return await self._events().read_before(stream_id, before, limit)

    async def get_event(self, event_id: UUID) -> RecordedEvent:
        """One event of this workspace's streams by its id, with the stream that holds it."""
        event = await self._events().read_by_id(event_id)
        if event is None:
            raise StreamEventNotFoundError(f"Event {event_id} not found")
        return event

    async def list_events_since(
        self, stream_id: UUID, *, since: datetime, after: int, limit: int
    ) -> list[RecordedEvent]:
        """Oldest first: received at or after ``since``, past position ``after``."""
        await self.get_stream(stream_id)
        return await self._events().read_since(stream_id, since, after, limit)
