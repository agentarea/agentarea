"""Streams, their sources and subscriptions, as one workspace sees them. Never commits."""

import secrets
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from agentarea_common.auth.permission import PermissionService
from agentarea_common.base import RepositoryFactory
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.di.container import resolve

from ..domain.enums import StreamKind, SubscriptionKind
from ..domain.errors import (
    ForwardLoopError,
    NotAForwardError,
    SourceFedByTriggerError,
    StreamInUseError,
    StreamNameTakenError,
    StreamNotFoundError,
    StreamSourceNotFoundError,
    SubscriptionNotFoundError,
    TriggerSubscriptionNotFoundError,
)
from ..domain.filters import EventFilter
from ..domain.models import JournaledEvent, TriggerBinding
from ..infrastructure.journal_repository import StreamJournal
from ..infrastructure.orm import (
    StreamORM,
    StreamSourceORM,
    StreamSubscriptionORM,
    SubscriptionOutcomeORM,
)
from ..infrastructure.repository import (
    StreamRepository,
    StreamSourceRepository,
    StreamSubscriptionRepository,
    SubscriptionOutcomeRepository,
)


def webhook_stream_name(trigger_name: str, webhook_id: str) -> str:
    """The name a webhook trigger's own stream gets; the backfill migration writes the same.

    ``streams.name`` is a ``varchar(255)``; the trigger name is truncated so the
    ``" (webhook_id)"`` suffix always survives intact, down to 0 characters of
    name. A ``webhook_id`` long enough that even the bare suffix would not fit
    has nothing left to truncate, so this raises instead of cutting the id.
    """
    suffix = f" ({webhook_id})"
    if len(suffix) > 255:
        raise ValueError(
            f"webhook_id {webhook_id!r} is {len(webhook_id)} characters; its stream-name "
            f"suffix alone is {len(suffix)} characters, past the 255-character limit"
        )
    name_budget = min(200, 255 - len(suffix))
    return f"{trigger_name[:name_budget]}{suffix}"


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

    def _journal(self) -> StreamJournal:
        return StreamJournal(self._session, self.repository_factory.user_context, self.settings)

    async def create_stream(
        self, *, name: str, description: str, retention_days: int | None
    ) -> StreamORM:
        return await self._streams().add_stream(
            name=name,
            description=description,
            kind=StreamKind.CUSTOM,
            retention_days=(
                retention_days if retention_days is not None else self.settings.RETENTION.days
            ),
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

        Refused while a live webhook trigger's source feeds the stream
        (``SourceFedByTriggerError``), or while a trigger subscribes to it or a
        forward writes into it (``StreamInUseError``): the subscription would
        cascade away and leave its trigger active but deaf, and a forward's
        outputs are not a foreign key, so it would keep retrying a missing stream.
        The stream row stays locked until commit, so none is added meanwhile.
        """
        if await self._streams().lock_for_delete(stream_id) is None:
            raise StreamNotFoundError(stream_id)
        if fed := await self.triggers_feeding(stream_id):
            raise SourceFedByTriggerError(f"Stream {stream_id}", sorted(set(fed.values())))
        triggers = await self._subscriptions().trigger_ids_on_stream(stream_id)
        forwards = await self._subscriptions().forwards_into(stream_id)
        if triggers or forwards:
            raise StreamInUseError(stream_id, triggers, [(f.id, f.stream_id) for f in forwards])

    async def delete_stream(self, stream_id: UUID) -> None:
        """Refused while anything depends on the stream; see ``ensure_deletable``."""
        await self.ensure_deletable(stream_id)
        if not await self._streams().delete_in_workspace(stream_id):
            raise StreamNotFoundError(stream_id)

    async def add_webhook_source(
        self, *, stream_id: UUID, webhook_type: str, validation_rules: dict[str, Any]
    ) -> StreamSourceORM:
        """A webhook source no trigger owns: its credentials are keyed by its own id."""
        await self.get_stream(stream_id)
        source_id = uuid4()
        return await self._sources().add_webhook_source(
            source_id=source_id,
            stream_id=stream_id,
            webhook_id=secrets.token_urlsafe(16),
            webhook_type=webhook_type,
            allowed_methods=["POST"],
            validation_rules=validation_rules,
            webhook_config=None,
            credential_key=source_id,
        )

    async def get_source(self, stream_id: UUID, source_id: UUID) -> StreamSourceORM:
        source = await self._sources().get_in_stream(stream_id, source_id)
        if source is None:
            raise StreamSourceNotFoundError(source_id)
        return source

    async def triggers_feeding(self, stream_id: UUID) -> dict[UUID, UUID]:
        """Each source of the stream that a live webhook trigger owns, to that trigger."""
        owned = {
            s.id: s.credential_key
            for s in await self._sources().list_for_stream(stream_id)
            if s.credential_key is not None and s.credential_key != s.id
        }
        live = await self._subscriptions().live_trigger_ids(list(set(owned.values())))
        return {source: trigger for source, trigger in owned.items() if trigger in live}

    async def delete_source(self, stream_id: UUID, source_id: UUID) -> StreamSourceORM:
        """Remove a source; one a live trigger owns goes with its trigger instead."""
        source = await self.get_source(stream_id, source_id)
        if trigger_id := (await self.triggers_feeding(stream_id)).get(source.id):
            raise SourceFedByTriggerError(f"Source {source_id}", [trigger_id])
        if not await self._sources().delete_in_workspace(source.id):
            raise StreamSourceNotFoundError(source_id)
        return source

    async def create_webhook_stream_for_trigger(
        self,
        *,
        trigger_id: UUID,
        trigger_name: str,
        webhook_id: str,
        webhook_type: str,
        allowed_methods: list[str],
        validation_rules: dict[str, Any],
        webhook_config: dict[str, Any] | None,
        event_types: list[str],
    ) -> tuple[StreamORM, StreamSourceORM, StreamSubscriptionORM]:
        """The trigger's stream, source and subscription.

        A stream a deleted trigger with the same name and webhook left behind is
        taken over, so the webhook's history continues; the new subscription
        starts after the events already there.
        """
        stream = await self.reusable_webhook_stream(trigger_name, webhook_id)
        cursor = 0
        if stream is None:
            stream = await self._streams().add_stream(
                name=webhook_stream_name(trigger_name, webhook_id),
                description=f"Webhook {webhook_type}",
                kind=StreamKind.CUSTOM,
                retention_days=self.settings.RETENTION.days,
            )
        else:
            cursor = await self._journal().last_sequence(stream.id)
        source = await self._sources().add_webhook_source(
            stream_id=stream.id,
            webhook_id=webhook_id,
            webhook_type=webhook_type,
            allowed_methods=allowed_methods,
            validation_rules=validation_rules,
            webhook_config=webhook_config,
            credential_key=trigger_id,
        )
        subscription = await self._subscriptions().add_subscription(
            stream_id=stream.id,
            kind=SubscriptionKind.TRIGGER,
            trigger_id=trigger_id,
            filter=EventFilter.from_trigger_event_types(event_types),
            output_stream_ids=[],
            cursor_sequence=cursor,
        )
        return stream, source, subscription

    async def reusable_webhook_stream(self, trigger_name: str, webhook_id: str) -> StreamORM | None:
        """The stream a webhook trigger with this name and webhook would take over, if any.

        Deleting a webhook trigger keeps its stream for the history. Re-creating
        it under the same name and webhook id (to keep the sender's URL) lands on
        that stream's name. It is taken over only while no webhook feeds it and
        the caller may write to it; otherwise the name conflict is refused.
        """
        name = webhook_stream_name(trigger_name, webhook_id)
        existing = await self._streams().get_by_name(name)
        if existing is None:
            return None
        if await self._sources().list_for_stream(existing.id):
            raise StreamNameTakenError(
                name,
                f"Stream {name!r} ({existing.id}) already exists and another source feeds "
                "it; give the trigger another name",
            )
        user_id = self.repository_factory.user_context.user_id
        if not await resolve(PermissionService).check(user_id, "edit", "stream", str(existing.id)):
            raise StreamNameTakenError(
                name,
                f"Stream {name!r} ({existing.id}) is left from a deleted trigger with this "
                "webhook and you may not write to it; give the trigger another name",
            )
        return existing

    async def subscribe_trigger(
        self, *, stream_id: UUID, trigger_id: UUID, event_filter: EventFilter
    ) -> StreamSubscriptionORM:
        await self.get_stream(stream_id)
        return await self._subscriptions().add_subscription(
            stream_id=stream_id,
            kind=SubscriptionKind.TRIGGER,
            trigger_id=trigger_id,
            filter=event_filter,
            output_stream_ids=[],
            cursor_sequence=await self._journal().last_sequence(stream_id),
        )

    async def update_trigger_filter(self, trigger_id: UUID, event_filter: EventFilter) -> None:
        if not await self._subscriptions().update_filter_for_trigger(trigger_id, event_filter):
            raise TriggerSubscriptionNotFoundError(trigger_id)

    async def sync_trigger_webhook_source(self, trigger_id: UUID, **fields: Any) -> None:
        sources = await self._sources().find_by_credential_key(trigger_id)
        for source in sources:
            await self._sources().update_webhook_fields(source.id, **fields)

    async def remove_trigger_webhook_sources(self, trigger_id: UUID) -> None:
        await self._sources().delete_by_credential_key(trigger_id)

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
        return await self._subscriptions().add_subscription(
            stream_id=stream_id,
            kind=SubscriptionKind.FORWARD,
            trigger_id=None,
            filter=event_filter,
            output_stream_ids=output_stream_ids,
            cursor_sequence=await self._journal().last_sequence(stream_id),
        )

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
        """Remove a forward; its outcomes go with it, the events it copied stay."""
        forward = await self.get_forward(stream_id, subscription_id)
        if not await self._subscriptions().delete_in_workspace(forward.id):
            raise SubscriptionNotFoundError(subscription_id)

    async def trigger_subscription(self, trigger_id: UUID) -> StreamSubscriptionORM | None:
        return await self._subscriptions().get_for_trigger(trigger_id)

    async def webhook_source_for_trigger(self, trigger_id: UUID) -> StreamSourceORM | None:
        sources = await self._sources().find_by_credential_key(trigger_id)
        return sources[0] if sources else None

    async def last_received_at(self, stream_id: UUID) -> datetime | None:
        await self.get_stream(stream_id)
        return await self._journal().last_received_at(stream_id)

    async def trigger_bindings(self, trigger_ids: list[UUID]) -> dict[UUID, TriggerBinding]:
        """Stream, filter, webhook id and last event of each trigger, in three queries."""
        if not trigger_ids:
            return {}
        subscriptions = await self._subscriptions().list_for_triggers(trigger_ids)
        sources = await self._sources().find_by_credential_keys(trigger_ids)
        last_by_stream = await self._journal().last_received_by_stream(
            list({s.stream_id for s in subscriptions})
        )
        webhook_by_trigger = {s.credential_key: s.webhook_id for s in sources}
        return {
            s.trigger_id: TriggerBinding(
                stream_id=s.stream_id,
                event_filter=s.filter,
                webhook_id=webhook_by_trigger.get(s.trigger_id),
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
    ) -> list[JournaledEvent]:
        """Oldest first after ``after``; otherwise newest first before ``before``."""
        await self.get_stream(stream_id)
        if after is not None:
            return await self._journal().read_after(stream_id, after, limit)
        return await self._journal().read_before(stream_id, before, limit)

    async def outcomes_for(
        self, stream_id: UUID, sequences: list[int]
    ) -> list[SubscriptionOutcomeORM]:
        repo = self.repository_factory.create_repository(SubscriptionOutcomeRepository)
        return await repo.list_for_events(stream_id, sequences)

    async def outcomes_of_subscription(
        self, subscription_id: UUID, limit: int
    ) -> list[SubscriptionOutcomeORM]:
        repo = self.repository_factory.create_repository(SubscriptionOutcomeRepository)
        return await repo.list_for_subscription(subscription_id, limit)
