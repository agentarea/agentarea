"""Workspace-scoped repositories for streams, sources, subscriptions and outcomes."""

from typing import Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import unscoped
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import SourceKind, StreamKind, SubscriptionKind, SubscriptionStatus
from ..domain.filters import EventFilter
from .orm import StreamORM, StreamSourceORM, StreamSubscriptionORM, SubscriptionOutcomeORM


async def find_webhook_source(session: AsyncSession, webhook_id: str) -> StreamSourceORM | None:
    """Find a webhook source before any tenant is known; the source names the workspace."""
    with unscoped("an inbound webhook names a source, not a workspace; the source's decides"):
        result = await session.execute(
            select(StreamSourceORM).where(
                StreamSourceORM.webhook_id == webhook_id,
                StreamSourceORM.kind == SourceKind.WEBHOOK.value,
            )
        )
    return result.scalar_one_or_none()


class StreamRepository(WorkspaceScopedRepository[StreamORM]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, StreamORM, user_context)

    async def add_stream(
        self, *, name: str, description: str, kind: StreamKind, retention_days: int
    ) -> StreamORM:
        stream = StreamORM(
            name=name,
            description=description,
            kind=kind.value,
            retention_days=retention_days,
            workspace_id=self.user_context.workspace_id,
            created_by=self.user_context.user_id,
        )
        self.session.add(stream)
        await self.session.flush()
        # Bypasses WorkspaceScopedRepository.create, so grant ownership explicitly.
        await self._record_graph_ownership(stream)
        return stream

    async def get_by_name(self, name: str) -> StreamORM | None:
        result = await self.session.execute(select(StreamORM).where(StreamORM.name == name))
        return result.scalar_one_or_none()


class StreamSourceRepository(WorkspaceScopedRepository[StreamSourceORM]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, StreamSourceORM, user_context)

    async def add_webhook_source(
        self,
        *,
        stream_id: UUID,
        webhook_id: str,
        webhook_type: str,
        allowed_methods: list[str],
        validation_rules: dict[str, Any],
        webhook_config: dict[str, Any] | None,
        credential_key: UUID,
    ) -> StreamSourceORM:
        source = StreamSourceORM(
            stream_id=stream_id,
            kind=SourceKind.WEBHOOK.value,
            webhook_id=webhook_id,
            webhook_type=webhook_type,
            allowed_methods=allowed_methods,
            validation_rules=validation_rules,
            webhook_config=webhook_config,
            credential_key=credential_key,
            workspace_id=self.user_context.workspace_id,
            created_by=self.user_context.user_id,
        )
        self.session.add(source)
        await self.session.flush()
        return source

    async def list_for_stream(self, stream_id: UUID) -> list[StreamSourceORM]:
        result = await self.session.execute(
            select(StreamSourceORM).where(StreamSourceORM.stream_id == stream_id)
        )
        return list(result.scalars().all())

    async def find_by_credential_key(self, key: UUID) -> list[StreamSourceORM]:
        result = await self.session.execute(
            select(StreamSourceORM).where(StreamSourceORM.credential_key == key)
        )
        return list(result.scalars().all())

    async def update_webhook_fields(self, source_id: UUID, **fields: Any) -> None:
        await self.session.execute(
            update(StreamSourceORM).where(StreamSourceORM.id == source_id).values(**fields)
        )


class StreamSubscriptionRepository(WorkspaceScopedRepository[StreamSubscriptionORM]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, StreamSubscriptionORM, user_context)

    async def add_subscription(
        self,
        *,
        stream_id: UUID,
        kind: SubscriptionKind,
        trigger_id: UUID | None,
        filter: EventFilter,
        output_stream_ids: list[UUID],
        cursor_sequence: int,
    ) -> StreamSubscriptionORM:
        subscription = StreamSubscriptionORM(
            stream_id=stream_id,
            kind=kind.value,
            trigger_id=trigger_id,
            filter=filter.model_dump(),
            output_stream_ids=[str(s) for s in output_stream_ids],
            cursor_sequence=cursor_sequence,
            status=SubscriptionStatus.ACTIVE.value,
            attempts=0,
            workspace_id=self.user_context.workspace_id,
            created_by=self.user_context.user_id,
        )
        self.session.add(subscription)
        await self.session.flush()
        return subscription

    async def get_for_trigger(self, trigger_id: UUID) -> StreamSubscriptionORM | None:
        result = await self.session.execute(
            select(StreamSubscriptionORM).where(StreamSubscriptionORM.trigger_id == trigger_id)
        )
        return result.scalar_one_or_none()

    async def list_for_stream(self, stream_id: UUID) -> list[StreamSubscriptionORM]:
        result = await self.session.execute(
            select(StreamSubscriptionORM)
            .where(StreamSubscriptionORM.stream_id == stream_id)
            .order_by(StreamSubscriptionORM.created_at)
        )
        return list(result.scalars().all())


class SubscriptionOutcomeRepository(WorkspaceScopedRepository[SubscriptionOutcomeORM]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, SubscriptionOutcomeORM, user_context)

    async def list_for_events(
        self, stream_id: UUID, sequences: list[int]
    ) -> list[SubscriptionOutcomeORM]:
        if not sequences:
            return []
        result = await self.session.execute(
            select(SubscriptionOutcomeORM).where(
                SubscriptionOutcomeORM.stream_id == stream_id,
                SubscriptionOutcomeORM.event_sequence.in_(sequences),
            )
        )
        return list(result.scalars().all())

    async def list_for_subscription(
        self, subscription_id: UUID, limit: int
    ) -> list[SubscriptionOutcomeORM]:
        result = await self.session.execute(
            select(SubscriptionOutcomeORM)
            .where(SubscriptionOutcomeORM.subscription_id == subscription_id)
            .order_by(SubscriptionOutcomeORM.event_sequence.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
