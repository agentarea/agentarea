"""Streams, their sources and subscriptions, as one workspace sees them. Never commits."""

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from agentarea_common.base import RepositoryFactory
from agentarea_common.config.streams import EventStreamSettings
from sqlalchemy import CursorResult, delete, func, select, update

from ..domain.enums import StreamKind, SubscriptionKind
from ..domain.errors import ForwardLoopError, StreamNotFoundError, TriggerSubscriptionNotFoundError
from ..domain.filters import EventFilter
from ..domain.models import JournaledEvent
from ..infrastructure.journal import StreamJournal
from ..infrastructure.orm import (
    StreamEventKeyORM,
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

    @property
    def _workspace_id(self) -> str:
        return self.repository_factory.user_context.workspace_id

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

    async def list_streams(
        self, *, limit: int, offset: int, ids: set[str] | None
    ) -> list[StreamORM]:
        return await self._streams().list_all(limit=limit, offset=offset, ids=ids)

    async def delete_stream(self, stream_id: UUID) -> None:
        result = await self._session.execute(
            delete(StreamORM).where(
                StreamORM.id == stream_id, StreamORM.workspace_id == self._workspace_id
            )
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            raise StreamNotFoundError(stream_id)

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
        stream = await self._streams().add_stream(
            name=webhook_stream_name(trigger_name, webhook_id),
            description=f"Webhook {webhook_type}",
            kind=StreamKind.CUSTOM,
            retention_days=self.settings.RETENTION.days,
        )
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
            cursor_sequence=0,
        )
        return stream, source, subscription

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
        result = await self._session.execute(
            update(StreamSubscriptionORM)
            .where(
                StreamSubscriptionORM.trigger_id == trigger_id,
                StreamSubscriptionORM.workspace_id == self._workspace_id,
            )
            .values(filter=event_filter.model_dump())
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            raise TriggerSubscriptionNotFoundError(trigger_id)

    async def sync_trigger_webhook_source(self, trigger_id: UUID, **fields: Any) -> None:
        sources = await self._sources().find_by_credential_key(trigger_id)
        for source in sources:
            await self._sources().update_webhook_fields(source.id, **fields)

    async def remove_trigger_webhook_sources(self, trigger_id: UUID) -> None:
        await self._session.execute(
            delete(StreamSourceORM).where(
                StreamSourceORM.credential_key == trigger_id,
                StreamSourceORM.workspace_id == self._workspace_id,
            )
        )

    async def create_forward(
        self, *, stream_id: UUID, output_stream_ids: list[UUID], event_filter: EventFilter
    ) -> StreamSubscriptionORM:
        if not output_stream_ids:
            raise ForwardLoopError("A forward needs at least one output stream")
        if stream_id in output_stream_ids:
            raise ForwardLoopError("A forward may not write into its own input stream")
        await self.get_stream(stream_id)
        for output in output_stream_ids:
            await self.get_stream(output)
        return await self._subscriptions().add_subscription(
            stream_id=stream_id,
            kind=SubscriptionKind.FORWARD,
            trigger_id=None,
            filter=event_filter,
            output_stream_ids=output_stream_ids,
            cursor_sequence=await self._journal().last_sequence(stream_id),
        )

    async def trigger_subscription(self, trigger_id: UUID) -> StreamSubscriptionORM | None:
        return await self._subscriptions().get_for_trigger(trigger_id)

    async def webhook_source_for_trigger(self, trigger_id: UUID) -> StreamSourceORM | None:
        sources = await self._sources().find_by_credential_key(trigger_id)
        return sources[0] if sources else None

    async def last_received_at(self, stream_id: UUID) -> datetime | None:
        await self.get_stream(stream_id)
        result = await self._session.execute(
            select(func.max(StreamEventKeyORM.received_at)).where(
                StreamEventKeyORM.stream_id == stream_id
            )
        )
        return result.scalar_one()

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
