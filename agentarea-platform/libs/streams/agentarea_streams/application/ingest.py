"""The one way into a stream: check it, keep the quota, name the event, publish it.

The event id is ``uuid5(stream, event key)``, or the id a processor derives for
its output, so a repeat is the same event and the bus publishes it once. The
workspace write quota is counted as each event is admitted, over a sliding
minute, across every stream of the workspace (``WriteQuota``).
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.events.ports import IntegrationEvent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.errors import StreamNotFoundError, StreamQuotaExceededError
from ..domain.keys import event_id_for
from ..domain.models import AppendResult, Attachment, StreamEvent
from ..infrastructure.bus import StreamBus
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
        source_type: str | None = None,
        session_key: str | None = None,
        sender: str | None = None,
        attachments: Sequence[Attachment] = (),
    ) -> AppendResult:
        if not event_key.strip():
            raise ValueError("event_key is required: name what distinguishes this event")
        await self._require_stream(stream_id)
        received_at = self.clock()
        await self._enforce_quota(received_at)
        resolved_id = event_id or event_id_for(stream_id, event_key)
        stream_event = StreamEvent(
            **event.model_dump(exclude={"id", "correlation_id"}),
            id=resolved_id,
            # An entry event starts the chain everything it causes carries.
            correlation_id=event.correlation_id or str(resolved_id),
            stream_id=stream_id,
            workspace_id=self.user_context.workspace_id,
            created_by=self.user_context.user_id,
            event_key=event_key,
            received_at=received_at,
            depth=depth,
            source_id=source_id,
            source_type=source_type,
            session_key=session_key,
            sender=sender,
            attachments=list(attachments),
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
        if not await self.bus.quota.take(
            self.user_context.workspace_id, self.settings.WRITE_QUOTA, now
        ):
            raise StreamQuotaExceededError(
                self.user_context.workspace_id, self.settings.WRITE_QUOTA
            )
