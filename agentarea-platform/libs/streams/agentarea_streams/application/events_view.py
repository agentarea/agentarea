"""The ``events-view`` group: every bus event into the ``stream_events`` read model.

Insert-once by event id, so a redelivery writes nothing twice. Nothing reads
the view to decide what to fire.
"""

import logging

from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.events.ports import IntegrationEvent
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..domain.models import consumed_stream_event
from ..infrastructure.event_repository import StreamEventRepository

logger = logging.getLogger(__name__)


class EventsView:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def handle(self, message: IntegrationEvent) -> None:
        event = consumed_stream_event(message)
        context = UserContext(user_id=event.created_by, workspace_id=event.workspace_id)
        with workspace_scope(event.workspace_id):
            async with self._session_factory() as session:
                await StreamEventRepository(session, context).record(event)
                await session.commit()

    async def give_up(self, message: IntegrationEvent) -> None:
        logger.error(
            "Event %s (%s) could not be written to the events view; dead-lettered",
            message.id,
            message.type,
        )
