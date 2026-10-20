"""Workspace-scoped repositories for streams, their sources and subscriptions."""

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import unscoped
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import CursorResult, delete, func, or_, select, update
from sqlalchemy import cast as sql_cast
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import SourceKind, StreamKind, SubscriptionKind, SubscriptionStatus
from ..domain.errors import StreamNameTakenError
from ..domain.filters import EventFilter
from .orm import StreamORM, StreamSourceORM, StreamSubscriptionORM


async def find_webhook_source(session: AsyncSession, webhook_id: str) -> StreamSourceORM | None:
    """Find a webhook source before any tenant is known; the source names the workspace."""
    with unscoped(
        "an inbound webhook names a source, not a workspace; the source's workspace decides"
    ):
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

    async def add_stream(self, *, name: str, description: str, kind: StreamKind) -> StreamORM:
        stream = StreamORM(
            name=name,
            description=description,
            kind=kind.value,
            workspace_id=self.user_context.workspace_id,
            created_by=self.user_context.user_id,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(stream)
                await self.session.flush()
        except IntegrityError as error:
            if "uq_streams_workspace_name" not in str(error.orig):
                raise
            raise StreamNameTakenError(name) from error
        # Bypasses WorkspaceScopedRepository.create, so grant ownership explicitly.
        await self._record_graph_ownership(stream)
        return stream

    async def get_platform(self) -> StreamORM | None:
        result = await self.session.execute(
            select(StreamORM).where(
                StreamORM.kind == StreamKind.PLATFORM.value, self._get_workspace_filter()
            )
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> StreamORM | None:
        result = await self.session.execute(
            select(StreamORM).where(StreamORM.name == name, self._get_workspace_filter())
        )
        return result.scalar_one_or_none()

    async def lock_for_delete(self, stream_id: UUID) -> StreamORM | None:
        """The row, locked until commit: a subscription or forward added to it meanwhile waits."""
        result = await self.session.execute(
            select(StreamORM)
            .where(StreamORM.id == stream_id, self._get_workspace_filter())
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def lock_existing(self, stream_ids: list[UUID]) -> set[UUID]:
        """Which of ``stream_ids`` exist here, each kept from deletion until commit."""
        if not stream_ids:
            return set()
        result = await self.session.execute(
            select(StreamORM.id)
            .where(StreamORM.id.in_(stream_ids), self._get_workspace_filter())
            .order_by(StreamORM.id)
            .with_for_update(key_share=True)
        )
        return set(result.scalars().all())

    async def names(self, stream_ids: list[UUID]) -> dict[UUID, str]:
        """The name of each of ``stream_ids`` that exists here."""
        if not stream_ids:
            return {}
        result = await self.session.execute(
            select(StreamORM.id, StreamORM.name).where(
                StreamORM.id.in_(stream_ids), self._get_workspace_filter()
            )
        )
        return {row.id: row.name for row in result}

    async def delete_in_workspace(self, stream_id: UUID) -> bool:
        result = await self.session.execute(
            delete(StreamORM).where(StreamORM.id == stream_id, self._get_workspace_filter())
        )
        return cast(CursorResult[Any], result).rowcount == 1


class StreamSourceRepository(WorkspaceScopedRepository[StreamSourceORM]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, StreamSourceORM, user_context)

    async def add_source(
        self,
        *,
        source_id: UUID,
        stream_id: UUID,
        kind: SourceKind,
        source_type: str,
        webhook_id: str | None,
        webhook_config: dict[str, Any],
        event_templates: dict[str, Any] | None,
    ) -> StreamSourceORM:
        """A source keys its credentials by its own id."""
        source = StreamSourceORM(
            id=source_id,
            stream_id=stream_id,
            kind=kind.value,
            webhook_id=webhook_id,
            webhook_type=source_type,
            webhook_config=webhook_config,
            credential_key=source_id,
            event_templates=event_templates,
            workspace_id=self.user_context.workspace_id,
            created_by=self.user_context.user_id,
        )
        self.session.add(source)
        await self.session.flush()
        return source

    async def list_for_stream(self, stream_id: UUID) -> list[StreamSourceORM]:
        result = await self.session.execute(
            select(StreamSourceORM).where(
                StreamSourceORM.stream_id == stream_id, self._get_workspace_filter()
            )
        )
        return list(result.scalars().all())

    async def get_in_stream(self, stream_id: UUID, source_id: UUID) -> StreamSourceORM | None:
        result = await self.session.execute(
            select(StreamSourceORM).where(
                StreamSourceORM.id == source_id,
                StreamSourceORM.stream_id == stream_id,
                self._get_workspace_filter(),
            )
        )
        return result.scalar_one_or_none()

    async def delete_in_workspace(self, source_id: UUID) -> bool:
        result = await self.session.execute(
            delete(StreamSourceORM).where(
                StreamSourceORM.id == source_id, self._get_workspace_filter()
            )
        )
        return cast(CursorResult[Any], result).rowcount == 1


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
        code: str | None = None,
    ) -> StreamSubscriptionORM:
        subscription = StreamSubscriptionORM(
            stream_id=stream_id,
            kind=kind.value,
            trigger_id=trigger_id,
            filter=filter.model_dump(),
            output_stream_ids=[str(s) for s in output_stream_ids],
            code=code,
            status=SubscriptionStatus.ACTIVE.value,
            workspace_id=self.user_context.workspace_id,
            created_by=self.user_context.user_id,
        )
        self.session.add(subscription)
        await self.session.flush()
        return subscription

    async def get_for_trigger(self, trigger_id: UUID) -> StreamSubscriptionORM | None:
        result = await self.session.execute(
            select(StreamSubscriptionORM).where(
                StreamSubscriptionORM.trigger_id == trigger_id, self._get_workspace_filter()
            )
        )
        return result.scalar_one_or_none()

    async def live_trigger_ids(self, candidates: list[UUID]) -> set[UUID]:
        """Which of ``candidates`` name a trigger that still has its subscription."""
        if not candidates:
            return set()
        result = await self.session.execute(
            select(StreamSubscriptionORM.trigger_id).where(
                StreamSubscriptionORM.trigger_id.in_(candidates), self._get_workspace_filter()
            )
        )
        return {t for t in result.scalars().all() if t is not None}

    async def list_for_triggers(self, trigger_ids: list[UUID]) -> list[StreamSubscriptionORM]:
        result = await self.session.execute(
            select(StreamSubscriptionORM).where(
                StreamSubscriptionORM.trigger_id.in_(trigger_ids), self._get_workspace_filter()
            )
        )
        return list(result.scalars().all())

    async def update_filter_for_trigger(self, trigger_id: UUID, event_filter: EventFilter) -> bool:
        result = await self.session.execute(
            update(StreamSubscriptionORM)
            .where(StreamSubscriptionORM.trigger_id == trigger_id, self._get_workspace_filter())
            .values(filter=event_filter.model_dump())
        )
        return cast(CursorResult[Any], result).rowcount == 1

    async def get_active(self, subscription_id: UUID) -> StreamSubscriptionORM | None:
        """The subscription while it exists, is active and has not expired; what the router re-checks."""
        result = await self.session.execute(
            select(StreamSubscriptionORM).where(
                StreamSubscriptionORM.id == subscription_id,
                StreamSubscriptionORM.status == SubscriptionStatus.ACTIVE.value,
                or_(
                    StreamSubscriptionORM.expires_at.is_(None),
                    StreamSubscriptionORM.expires_at > func.now(),
                ),
                self._get_workspace_filter(),
            )
        )
        return result.scalar_one_or_none()

    async def get_external(self, external_id: str) -> StreamSubscriptionORM | None:
        result = await self.session.execute(
            select(StreamSubscriptionORM).where(
                StreamSubscriptionORM.external_id == external_id,
                StreamSubscriptionORM.kind == SubscriptionKind.EXTERNAL.value,
                self._get_workspace_filter(),
            )
        )
        return result.scalar_one_or_none()

    async def count_external(self) -> int:
        result = await self.session.execute(
            select(func.count()).where(
                StreamSubscriptionORM.kind == SubscriptionKind.EXTERNAL.value,
                self._get_workspace_filter(),
            )
        )
        return int(result.scalar_one())

    async def external_on_stream(self, stream_id: UUID) -> list[StreamSubscriptionORM]:
        result = await self.session.execute(
            select(StreamSubscriptionORM).where(
                StreamSubscriptionORM.stream_id == stream_id,
                StreamSubscriptionORM.kind == SubscriptionKind.EXTERNAL.value,
                self._get_workspace_filter(),
            )
        )
        return list(result.scalars().all())

    async def endpoint_verified(self, subscriber: str, callback_url: str) -> bool:
        """Whether this subscriber's endpoint already answered a challenge here."""
        result = await self.session.execute(
            select(StreamSubscriptionORM.id)
            .where(
                StreamSubscriptionORM.kind == SubscriptionKind.EXTERNAL.value,
                StreamSubscriptionORM.subscriber == subscriber,
                StreamSubscriptionORM.callback_url == callback_url,
                StreamSubscriptionORM.verified_at.is_not(None),
                self._get_workspace_filter(),
            )
            .limit(1)
        )
        return result.first() is not None

    async def add_external(
        self,
        *,
        stream_id: UUID,
        filter: EventFilter,
        external_id: str,
        subscriber: str,
        callback_url: str,
        secret_name: str,
        expires_at: datetime,
        verified_at: datetime,
    ) -> StreamSubscriptionORM:
        subscription = StreamSubscriptionORM(
            stream_id=stream_id,
            kind=SubscriptionKind.EXTERNAL.value,
            trigger_id=None,
            filter=filter.model_dump(),
            output_stream_ids=[],
            status=SubscriptionStatus.ACTIVE.value,
            external_id=external_id,
            subscriber=subscriber,
            callback_url=callback_url,
            secret_name=secret_name,
            expires_at=expires_at,
            verified_at=verified_at,
            workspace_id=self.user_context.workspace_id,
            created_by=self.user_context.user_id,
        )
        self.session.add(subscription)
        await self.session.flush()
        return subscription

    async def record_delivery(
        self, subscription_id: UUID, *, at: datetime, error: str | None
    ) -> None:
        """A delivery attempt's outcome: a success clears the error, a failure keeps its first time."""
        values: dict[str, Any] = (
            {"last_delivery_at": at, "last_error": None, "failed_since": None}
            if error is None
            else {
                "last_error": error,
                "failed_since": func.coalesce(StreamSubscriptionORM.failed_since, at),
            }
        )
        await self.session.execute(
            update(StreamSubscriptionORM)
            .where(StreamSubscriptionORM.id == subscription_id, self._get_workspace_filter())
            .values(**values)
        )

    async def mark_failed(self, subscription_id: UUID) -> None:
        await self.session.execute(
            update(StreamSubscriptionORM)
            .where(StreamSubscriptionORM.id == subscription_id, self._get_workspace_filter())
            .values(status=SubscriptionStatus.FAILED.value)
        )

    async def list_for_stream(self, stream_id: UUID) -> list[StreamSubscriptionORM]:
        result = await self.session.execute(
            select(StreamSubscriptionORM)
            .where(StreamSubscriptionORM.stream_id == stream_id, self._get_workspace_filter())
            .order_by(StreamSubscriptionORM.created_at)
        )
        return list(result.scalars().all())

    async def get_in_stream(
        self, stream_id: UUID, subscription_id: UUID
    ) -> StreamSubscriptionORM | None:
        result = await self.session.execute(
            select(StreamSubscriptionORM).where(
                StreamSubscriptionORM.id == subscription_id,
                StreamSubscriptionORM.stream_id == stream_id,
                self._get_workspace_filter(),
            )
        )
        return result.scalar_one_or_none()

    async def trigger_ids_on_stream(self, stream_id: UUID) -> list[UUID]:
        result = await self.session.execute(
            select(StreamSubscriptionORM.trigger_id)
            .where(
                StreamSubscriptionORM.stream_id == stream_id,
                StreamSubscriptionORM.kind == SubscriptionKind.TRIGGER.value,
                self._get_workspace_filter(),
            )
            .order_by(StreamSubscriptionORM.created_at)
        )
        return [t for t in result.scalars().all() if t is not None]

    async def forwards_into(self, stream_id: UUID) -> list[StreamSubscriptionORM]:
        """Forwards and processors of any stream here that list ``stream_id`` among their outputs."""
        result = await self.session.execute(
            select(StreamSubscriptionORM)
            .where(
                StreamSubscriptionORM.kind.in_(
                    [SubscriptionKind.FORWARD.value, SubscriptionKind.PROCESSOR.value]
                ),
                sql_cast(StreamSubscriptionORM.output_stream_ids, JSONB).contains([str(stream_id)]),
                self._get_workspace_filter(),
            )
            .order_by(StreamSubscriptionORM.created_at)
        )
        return list(result.scalars().all())

    async def delete_in_workspace(self, subscription_id: UUID) -> bool:
        result = await self.session.execute(
            delete(StreamSubscriptionORM).where(
                StreamSubscriptionORM.id == subscription_id, self._get_workspace_filter()
            )
        )
        return cast(CursorResult[Any], result).rowcount == 1


async def expired_external(session: AsyncSession) -> list[StreamSubscriptionORM]:
    """EXTERNAL subscriptions past their expiry, in every workspace; the sweeper removes them."""
    with unscoped("expired subscribers are reclaimed in every workspace by one sweeper"):
        result = await session.execute(
            select(StreamSubscriptionORM).where(
                StreamSubscriptionORM.kind == SubscriptionKind.EXTERNAL.value,
                StreamSubscriptionORM.expires_at <= func.now(),
            )
        )
    return list(result.scalars().all())
