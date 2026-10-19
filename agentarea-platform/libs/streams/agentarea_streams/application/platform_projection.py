"""The ``platform`` group on ``tasks.events``: task outcomes into the workspace's platform stream.

ADR-0040 §1 (``SourceKind.PLATFORM``) and §5: a task that completed, failed,
was cancelled or waits for an approval or an answer becomes an event of the
``platform`` stream of its workspace, created on first use. It goes in through
the same ``ingest`` as every source, so its id is ``uuid5(stream, key)`` with
the task event's id as the key, and a redelivery publishes nothing twice.

The event carries the task's ``correlation_id``, the task event as its
``causation_id``, and the depth of the event that started the task plus one,
so a trigger on the platform stream extends a bounded chain. Its ``data.body``
is the task summary of ``domain.platform``. Every other task event is
acknowledged and dropped. Only the platform group writes this stream.
"""

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.constants import PLATFORM_PRINCIPAL_ID
from agentarea_common.events.ports import IntegrationEvent, UnprocessableEventError
from agentarea_common.events.task_stream import WORKSPACE_EXTENSION
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..domain.platform import (
    PLATFORM_SOURCE_TYPE,
    PlatformTask,
    platform_event_data,
    platform_event_key,
    projects,
)
from ..infrastructure.bus import StreamBus
from .ingest import StreamIngest
from .stream_service import StreamService

logger = logging.getLogger(__name__)

LoadTask = Callable[[AsyncSession, UUID, str], Awaitable[PlatformTask | None]]


class PlatformProjection:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        settings: EventStreamSettings,
        bus: StreamBus,
        load_task: LoadTask,
    ):
        self._session_factory = session_factory
        self._settings = settings
        self._bus = bus
        self._load_task = load_task

    async def handle(self, message: IntegrationEvent) -> None:
        if not projects(message.type):
            return
        workspace_id = message.extensions.get(WORKSPACE_EXTENSION)
        try:
            task_id = UUID(message.subject or "")
        except ValueError as error:
            raise UnprocessableEventError(f"task event {message.id} names no task") from error
        if not workspace_id:
            raise UnprocessableEventError(f"task event {message.id} names no workspace")
        async with self._session_factory() as session:
            with workspace_scope(workspace_id):
                task = await self._load_task(session, task_id, workspace_id)
                if task is None:
                    logger.info("Task %s of event %s is gone; not projected", task_id, message.id)
                    return
                platform = UserContext(user_id=PLATFORM_PRINCIPAL_ID, workspace_id=workspace_id)
                stream, source = await StreamService(
                    RepositoryFactory(session, platform), self._settings
                ).ensure_platform_stream()
                stream_id, source_id = stream.id, source.id
                await session.commit()
                await StreamIngest(
                    session,
                    UserContext(user_id=task.owner, workspace_id=workspace_id),
                    self._settings,
                    self._bus,
                ).append(
                    stream_id,
                    IntegrationEvent(
                        type=message.type,
                        source=PLATFORM_SOURCE_TYPE,
                        subject=str(task.id),
                        time=message.time,
                        correlation_id=task.correlation_id,
                        causation_id=str(message.id),
                        traceparent=message.traceparent,
                        data={"body": platform_event_data(message.type, task, message.data)},
                    ),
                    event_key=platform_event_key(message.type, message.id, message.data),
                    source_id=source_id,
                    source_type=PLATFORM_SOURCE_TYPE,
                    depth=task.event_depth,
                )

    async def give_up(self, message: IntegrationEvent) -> None:
        logger.error(
            "Task event %s (%s of task %s) was not projected into the platform stream after "
            + "the delivery limit; dead-lettered",
            message.id,
            message.type,
            message.subject,
        )
