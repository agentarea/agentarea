"""The Postgres journal as the EventStream port: catch-up from a cursor, then live.

Set STREAMS_TEST_DATABASE_URL.
"""

import asyncio
import os
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.events.ports import EventStream, IntegrationEvent
from agentarea_streams.application.stream_service import StreamService
from agentarea_streams.infrastructure.journal_repository import StreamJournal
from agentarea_streams.infrastructure.pg_journal import PgJournalEventStream
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")


async def test_reads_catch_up_from_the_offset_then_tail_live():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    settings = EventStreamSettings(DISPATCH_EVERY=timedelta(milliseconds=50))
    with workspace_scope(ctx.workspace_id):
        async with maker() as session:
            with patch(
                "agentarea_common.base.workspace_scoped_repository.grant_resource_owner",
                new=AsyncMock(),
            ):
                stream = await StreamService(
                    RepositoryFactory(session, ctx), settings
                ).create_stream(name="tail", description="", retention_days=7)
            journal = StreamJournal(session, ctx, settings)
            first = await journal.append(stream.id, IntegrationEvent(type="a", source="t"),
                                         event_key="1")
            await journal.append(stream.id, IntegrationEvent(type="b", source="t"), event_key="2")
            await session.commit()

        port: EventStream = PgJournalEventStream(
            session_factory=maker, user_context=ctx, settings=settings
        )
        reader = port.read(stream=str(stream.id), from_offset=str(first.sequence))
        assert (await anext(reader)).type == "b"

        async def append_live():
            await asyncio.sleep(0.1)
            async with maker() as session:
                await StreamJournal(session, ctx, settings).append(
                    stream.id, IntegrationEvent(type="c", source="t"), event_key="3"
                )
                await session.commit()

        appender = asyncio.create_task(append_live())
        live = await asyncio.wait_for(anext(reader), timeout=5)
        await appender
        assert live.type == "c"
    await engine.dispose()
