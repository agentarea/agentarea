"""The one way into a stream: check it, keep the quota, name the event, publish it.

The event id is ``uuid5(stream, event key)``, or the id a processor derives for
its output, so a repeat is the same event and the bus publishes it once. The
workspace write quota counts what the events read model received in the last
minute, across every stream of the workspace.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.events.ports import IntegrationEvent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.errors import PayloadTooLargeError, StreamNotFoundError, StreamQuotaExceededError
from ..domain.keys import MAX_EVENT_BYTES, encoded_size, event_id_for
from ..domain.models import AppendResult, StreamEvent
from ..infrastructure.bus import StreamBus
from ..infrastructure.event_repository import StreamEventRepository
from ..infrastructure.orm import StreamORM


def _now() -> datetime:
    return datetime.now(UTC)


class StreamIngest:
    def __init__(
        self,
        session: AsyncSession,
        user_context: UserContext,
        settings: EventStreamSettings,
        bus: StreamBus,
        clock: Callable[[], datetime] = _now,
    ):
        self.session = session
        self.user_context = user_context
        self.settings = settings
        self.bus = bus
        self.clock = clock

    async def append(
        self,
        stream_id: UUID,
        event: IntegrationEvent,
        *,
        event_key: str,
        source_id: UUID | None = None,
        depth: int = 0,
        event_id: UUID | None = None,
    ) -> AppendResult:
        if not event_key.strip():
            raise ValueError("event_key is required: name what distinguishes this event")
        size = encoded_size(event.data)
        if size > MAX_EVENT_BYTES:
            raise PayloadTooLargeError(size)
        await self._require_stream(stream_id)
        received_at = self.clock()
        await self._enforce_quota(received_at)
        stream_event = StreamEvent(
            **event.model_dump(exclude={"id"}),
            id=event_id or event_id_for(stream_id, event_key),
            stream_id=stream_id,
            workspace_id=self.user_context.workspace_id,
            created_by=self.user_context.user_id,
            event_key=event_key,
            received_at=received_at,
            depth=depth,
            source_id=source_id,
        )
        appended = await self.bus.publish(stream_event)
        return AppendResult(event_id=stream_event.id, appended=appended)

    async def _require_stream(self, stream_id: UUID) -> None:
        found = await self.session.execute(
            select(StreamORM.id).where(
                StreamORM.id == stream_id, StreamORM.workspace_id == self.user_context.workspace_id
            )
        )
        if found.one_or_none() is None:
            raise StreamNotFoundError(stream_id)

    async def _enforce_quota(self, now: datetime) -> None:
        recent = await StreamEventRepository(self.session, self.user_context).count_since(
            now - timedelta(minutes=1)
        )
        if recent >= self.settings.WRITE_QUOTA:
            raise StreamQuotaExceededError(
                self.user_context.workspace_id, self.settings.WRITE_QUOTA
            )
