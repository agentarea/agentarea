"""Readers that page a stream oldest first by ``sequence > after`` never skip a row.

The events view and the router both write ``stream_events``. A sequence is
taken when the row is inserted, so an insert that commits after a higher
sequence was already read would fall behind a reader's cursor for good. Inserts
into one stream commit in sequence order. Set STREAMS_TEST_DATABASE_URL.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import tenant_scoped_session_class, workspace_scope
from agentarea_common.config.database import TenantScopeMode
from agentarea_streams.application.events_poll import read_page
from agentarea_streams.domain import StreamEvent, StreamKind
from agentarea_streams.domain.keys import event_id_for
from agentarea_streams.infrastructure.event_repository import StreamEventRepository
from agentarea_streams.infrastructure.repository import StreamRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")
GRANT = "agentarea_common.base.workspace_scoped_repository.grant_resource_owner"


@pytest.fixture
async def maker():
    engine = create_async_engine(TEST_DATABASE_URL)
    yield async_sessionmaker(
        engine,
        class_=AsyncSession,
        sync_session_class=tenant_scoped_session_class(TenantScopeMode.ENFORCE),
        expire_on_commit=False,
    )
    await engine.dispose()


@pytest.fixture
def ctx():
    context = UserContext(user_id="u", workspace_id=str(uuid4()))
    with workspace_scope(context.workspace_id):
        yield context


async def _stream(maker, ctx):
    async with maker() as session:
        with patch(GRANT, new=AsyncMock()):
            stream = await StreamRepository(session, ctx).add_stream(
                name=f"s-{uuid4()}", description="", kind=StreamKind.CUSTOM
            )
        await session.commit()
    return stream


def _event(stream_id, ctx, key):
    return StreamEvent(
        id=event_id_for(stream_id, key),
        type="push",
        source="test",
        data={"key": key},
        stream_id=stream_id,
        workspace_id=ctx.workspace_id,
        created_by=ctx.user_id,
        event_key=key,
        received_at=datetime.now(UTC),
    )


async def _routed_and_committed(maker, ctx, event):
    async with maker() as session:
        await StreamEventRepository(session, ctx).mark_routed(event, 0, at=datetime.now(UTC))
        await session.commit()


async def _after(maker, ctx, stream_id, after):
    async with maker() as session:
        return await StreamEventRepository(session, ctx).read_after(stream_id, after, 100)


async def _poll(maker, ctx, stream_id, after):
    async with maker() as session:
        return await read_page(
            StreamEventRepository(session, ctx),
            stream_id,
            after=after,
            since=datetime.now(UTC) - timedelta(days=1),
            admits=lambda _event: True,
            max_events=100,
        )


async def _interleaved(maker, ctx, read_twice):
    """The events view holds an insert open while the router writes a later one."""
    stream = await _stream(maker, ctx)
    early, late = _event(stream.id, ctx, "early"), _event(stream.id, ctx, "late")
    async with maker() as view:
        await StreamEventRepository(view, ctx).record(early)
        router = asyncio.create_task(_routed_and_committed(maker, ctx, late))
        await asyncio.wait({router}, timeout=0.5)
        seen = await read_twice(stream.id, first=True)
        await view.commit()
    await router
    seen += await read_twice(stream.id, first=False)
    return [early.id, late.id], seen


async def test_read_after_does_not_skip_a_row_that_commits_late(maker, ctx):
    cursor = 0

    async def read(stream_id, *, first):
        nonlocal cursor
        rows = await _after(maker, ctx, stream_id, cursor)
        if rows:
            cursor = rows[-1].sequence
        return [row.id for row in rows]

    written, seen = await _interleaved(maker, ctx, read)

    assert seen == written


async def test_events_poll_does_not_skip_a_row_that_commits_late(maker, ctx):
    cursor = 0

    async def read(stream_id, *, first):
        nonlocal cursor
        page = await _poll(maker, ctx, stream_id, cursor)
        cursor = page.position
        return [row.id for row in page.events]

    written, seen = await _interleaved(maker, ctx, read)

    assert seen == written


async def test_an_open_insert_holds_back_only_its_own_stream(maker, ctx):
    held, free = await _stream(maker, ctx), await _stream(maker, ctx)
    async with maker() as view:
        await StreamEventRepository(view, ctx).record(_event(held.id, ctx, "open"))
        other = asyncio.create_task(_routed_and_committed(maker, ctx, _event(free.id, ctx, "x")))
        done, _pending = await asyncio.wait({other}, timeout=5)
        await view.rollback()
    assert other in done
    await other
