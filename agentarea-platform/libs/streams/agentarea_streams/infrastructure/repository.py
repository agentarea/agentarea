"""Workspace-scoped repositories for streams, sources, subscriptions and outcomes."""

from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import unscoped
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import ColumnElement, CursorResult, delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import SourceKind, StreamKind, SubscriptionKind, SubscriptionStatus, Verdict
from ..domain.filters import EventFilter
from .orm import StreamORM, StreamSourceORM, StreamSubscriptionORM, SubscriptionOutcomeORM

WEBHOOK_FIELDS = frozenset(
    {"webhook_type", "allowed_methods", "validation_rules", "webhook_config", "credential_key"}
)


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
        result = await self.session.execute(
            select(StreamORM).where(StreamORM.name == name, self._get_workspace_filter())
        )
        return result.scalar_one_or_none()

    async def delete_in_workspace(self, stream_id: UUID) -> bool:
        result = await self.session.execute(
            delete(StreamORM).where(StreamORM.id == stream_id, self._get_workspace_filter())
        )
        return cast(CursorResult[Any], result).rowcount == 1


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
            select(StreamSourceORM).where(
                StreamSourceORM.stream_id == stream_id, self._get_workspace_filter()
            )
        )
        return list(result.scalars().all())

    async def find_by_credential_key(self, key: UUID) -> list[StreamSourceORM]:
        result = await self.session.execute(
            select(StreamSourceORM).where(
                StreamSourceORM.credential_key == key, self._get_workspace_filter()
            )
        )
        return list(result.scalars().all())

    async def find_by_credential_keys(self, keys: list[UUID]) -> list[StreamSourceORM]:
        result = await self.session.execute(
            select(StreamSourceORM).where(
                StreamSourceORM.credential_key.in_(keys), self._get_workspace_filter()
            )
        )
        return list(result.scalars().all())

    async def delete_by_credential_key(self, key: UUID) -> None:
        await self.session.execute(
            delete(StreamSourceORM).where(
                StreamSourceORM.credential_key == key, self._get_workspace_filter()
            )
        )

    async def update_webhook_fields(self, source_id: UUID, **fields: Any) -> None:
        unknown = sorted(set(fields) - WEBHOOK_FIELDS)
        if unknown:
            raise ValueError(f"Not webhook fields of a stream source: {', '.join(unknown)}")
        result = await self.session.execute(
            update(StreamSourceORM)
            .where(StreamSourceORM.id == source_id, self._get_workspace_filter())
            .values(**fields)
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            raise NoResultFound(f"Stream source {source_id} not found in workspace")


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
            select(StreamSubscriptionORM).where(
                StreamSubscriptionORM.trigger_id == trigger_id, self._get_workspace_filter()
            )
        )
        return result.scalar_one_or_none()

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

    def _leased_by(self, subscription_id: UUID, owner: str) -> tuple[ColumnElement[bool], ...]:
        return (
            StreamSubscriptionORM.id == subscription_id,
            self._get_workspace_filter(),
            StreamSubscriptionORM.lease_owner == owner,
        )

    async def renew_lease(
        self, subscription_id: UUID, owner: str, *, now: datetime, until: datetime
    ) -> bool:
        """Extend a lease still ``owner``'s and unexpired; False when it lapsed."""
        renewed = await self.session.execute(
            update(StreamSubscriptionORM)
            .where(
                *self._leased_by(subscription_id, owner), StreamSubscriptionORM.leased_until > now
            )
            .values(leased_until=until)
        )
        return cast(CursorResult[Any], renewed).rowcount == 1

    async def cursor_of(self, subscription_id: UUID) -> int:
        result = await self.session.execute(
            select(StreamSubscriptionORM.cursor_sequence).where(
                StreamSubscriptionORM.id == subscription_id, self._get_workspace_filter()
            )
        )
        return result.scalar_one()

    async def advance_cursor(
        self, subscription_id: UUID, owner: str, sequence: int, *, now: datetime, until: datetime
    ) -> bool:
        """Move the cursor and clear the failure state; False when the lease is not ``owner``'s."""
        moved = await self.session.execute(
            update(StreamSubscriptionORM)
            .where(*self._leased_by(subscription_id, owner))
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

    async def lock_if_leased(
        self, subscription_id: UUID, owner: str
    ) -> StreamSubscriptionORM | None:
        """The row, locked until commit, while ``owner`` still holds its lease."""
        result = await self.session.execute(
            select(StreamSubscriptionORM)
            .where(*self._leased_by(subscription_id, owner))
            # Held until commit: a claimer skips the row instead of taking it
            # between this read and the caller's write.
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def release_lease(self, subscription_id: UUID, owner: str) -> None:
        await self.session.execute(
            update(StreamSubscriptionORM)
            .where(*self._leased_by(subscription_id, owner))
            .values(leased_until=None, lease_owner=None)
        )

    async def list_for_stream(self, stream_id: UUID) -> list[StreamSubscriptionORM]:
        result = await self.session.execute(
            select(StreamSubscriptionORM)
            .where(StreamSubscriptionORM.stream_id == stream_id, self._get_workspace_filter())
            .order_by(StreamSubscriptionORM.created_at)
        )
        return list(result.scalars().all())


class SubscriptionOutcomeRepository(WorkspaceScopedRepository[SubscriptionOutcomeORM]):
    """Outcomes are unique per (subscription, event); the first one recorded stands."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, SubscriptionOutcomeORM, user_context)

    def _of_event(
        self, subscription_id: UUID, event_sequence: int
    ) -> tuple[ColumnElement[bool], ...]:
        return (
            SubscriptionOutcomeORM.subscription_id == subscription_id,
            SubscriptionOutcomeORM.event_sequence == event_sequence,
            self._get_workspace_filter(),
        )

    async def record_once(
        self,
        *,
        subscription_id: UUID,
        stream_id: UUID,
        event_sequence: int,
        verdict: Verdict,
        reason: str | None,
        score: float | None,
        task_id: UUID | None,
        derived_sequences: list[int],
        now: datetime,
    ) -> bool:
        """Insert unless the event already has an outcome; True when this call wrote it."""
        inserted = await self.session.execute(
            pg_insert(SubscriptionOutcomeORM)
            .values(
                id=uuid4(),
                subscription_id=subscription_id,
                stream_id=stream_id,
                event_sequence=event_sequence,
                verdict=verdict.value,
                reason=reason,
                score=score,
                task_id=task_id,
                derived_sequences=derived_sequences,
                workspace_id=self.user_context.workspace_id,
                created_by=self.user_context.user_id,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_subscription_outcomes_event")
            .returning(SubscriptionOutcomeORM.id)
        )
        return inserted.scalar_one_or_none() is not None

    async def reacted_task(self, subscription_id: UUID, event_sequence: int) -> UUID | None:
        result = await self.session.execute(
            select(SubscriptionOutcomeORM.task_id).where(
                *self._of_event(subscription_id, event_sequence),
                SubscriptionOutcomeORM.verdict == Verdict.REACTED.value,
            )
        )
        return result.scalar_one_or_none()

    async def delete_for_event(self, subscription_id: UUID, event_sequence: int) -> None:
        await self.session.execute(
            delete(SubscriptionOutcomeORM).where(*self._of_event(subscription_id, event_sequence))
        )

    async def list_for_events(
        self, stream_id: UUID, sequences: list[int]
    ) -> list[SubscriptionOutcomeORM]:
        if not sequences:
            return []
        result = await self.session.execute(
            select(SubscriptionOutcomeORM).where(
                SubscriptionOutcomeORM.stream_id == stream_id,
                SubscriptionOutcomeORM.event_sequence.in_(sequences),
                self._get_workspace_filter(),
            )
        )
        return list(result.scalars().all())

    async def list_for_subscription(
        self, subscription_id: UUID, limit: int
    ) -> list[SubscriptionOutcomeORM]:
        result = await self.session.execute(
            select(SubscriptionOutcomeORM)
            .where(
                SubscriptionOutcomeORM.subscription_id == subscription_id,
                self._get_workspace_filter(),
            )
            .order_by(SubscriptionOutcomeORM.event_sequence.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
