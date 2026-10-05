"""The Postgres journal behind the EventStream port; the cursor is the sequence."""

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.events.ports import IntegrationEvent
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .journal_repository import StreamJournal


class PgJournalEventStream:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        user_context: UserContext,
        settings: EventStreamSettings,
        wake: asyncio.Event | None = None,
    ):
        self._session_factory = session_factory
        self._user_context = user_context
        self._settings = settings
        self._wake = wake

    async def read(self, *, stream: str, from_offset: str = "0") -> AsyncIterator[IntegrationEvent]:
        stream_id = UUID(stream)
        cursor = int(from_offset)
        batch = self._settings.DISPATCH_BATCH
        while True:
            with workspace_scope(self._user_context.workspace_id):
                async with self._session_factory() as session:
                    events = await StreamJournal(
                        session, self._user_context, self._settings
                    ).read_after(stream_id, cursor, batch)
            for event in events:
                cursor = event.sequence
                yield event
            if len(events) < batch:
                await self._idle()

    async def _idle(self) -> None:
        timeout = self._settings.DISPATCH_EVERY.total_seconds()
        if self._wake is None:
            await asyncio.sleep(timeout)
            return
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=timeout)
        except TimeoutError:
            return
        finally:
            self._wake.clear()
