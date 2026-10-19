"""The workspace feed against the migrated schema.

Every event of the streams the caller may read, newest first, filtered by
stream, provider, kind (exact or ``prefix.*``), sender, session, time, by
what the platform did with it and with or without the platform's own events; the SQL result filter agrees with the status the
API reports for each row. Set STREAMS_TEST_DATABASE_URL.
"""

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import tenant_scoped_session_class, workspace_scope
from agentarea_common.config.database import TenantScopeMode
from agentarea_streams.domain import ReactionTally, StreamEvent, StreamKind
from agentarea_streams.domain.feed import FeedFilter
from agentarea_streams.domain.keys import event_id_for
from agentarea_streams.domain.processing import ProcessingStatus
from agentarea_streams.infrastructure.event_repository import StreamEventRepository
from agentarea_streams.infrastructure.repository import StreamRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")
GRANT = "agentarea_common.base.workspace_scoped_repository.grant_resource_owner"

# key: (kind, stream, source_type, sender, session, subscribers, tally)
_EVENTS = {
    "queued": ("order.paid", "orders", "generic_webhook", "alice", "s:1", None, None),
    "processing": ("order.refunded", "orders", "generic_webhook", "bob", "s:1", 3, (1, 0, 0)),
    "handled": ("message", "mail", "mail", "carol", None, 2, (2, 1, 0)),
    "error": ("message", "mail", "mail", "carol", "s:2", 3, (2, 0, 1)),
    "no_handlers": ("orders.closed", "orders", "generic_webhook", None, None, 0, None),
    "skipped": ("push", "hidden", "repo", "dave", None, 2, (2, 2, 0)),
}


@pytest.fixture
async def world():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        sync_session_class=tenant_scoped_session_class(TenantScopeMode.ENFORCE),
        expire_on_commit=False,
    )
    raw = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    other = UserContext(user_id="u", workspace_id=str(uuid4()))
    base = datetime.now(UTC) - timedelta(minutes=10)
    ids = {}
    with patch(GRANT, new=AsyncMock()):
        for context in (ctx, other):
            with workspace_scope(context.workspace_id):
                async with maker() as session:
                    streams = {
                        name: await StreamRepository(session, context).add_stream(
                            name=name, description="", kind=StreamKind.CUSTOM
                        )
                        for name in ("orders", "mail", "hidden")
                    }
                    repo = StreamEventRepository(session, context)
                    for i, (key, spec) in enumerate(_EVENTS.items()):
                        kind, stream, source_type, sender, session_key, subs, tally = spec
                        event = StreamEvent(
                            id=event_id_for(streams[stream].id, key),
                            type=kind,
                            source="test",
                            data={"n": i},
                            stream_id=streams[stream].id,
                            workspace_id=context.workspace_id,
                            created_by="u",
                            event_key=key,
                            received_at=base + timedelta(minutes=i),
                            source_type=source_type,
                            sender=sender,
                            session_key=session_key,
                        )
                        await repo.record(event)
                        if subs is not None:
                            await repo.mark_routed(event, subs, at=event.received_at)
                        if tally is not None:
                            reacted, skipped, errors = tally
                            await repo.mark_reactions(
                                event, ReactionTally(reacted=reacted, skipped=skipped, errors=errors)
                            )
                        if context is ctx:
                            ids[key] = event.id
                    await session.commit()
                    if context is ctx:
                        mine = streams
    with workspace_scope(ctx.workspace_id):
        yield SimpleNamespace(maker=maker, ctx=ctx, streams=mine, ids=ids, base=base)
    async with raw() as session:
        for context in (ctx, other):
            await session.execute(
                text("DELETE FROM streams WHERE workspace_id = :ws"), {"ws": context.workspace_id}
            )
        await session.commit()
    await engine.dispose()


def _readable(world, *names):
    return [world.streams[n].id for n in names or ("orders", "mail", "hidden")]


async def _keys(world, feed_filter=None, streams=None, before=None, limit=50):
    async with world.maker() as session:
        rows = await StreamEventRepository(session, world.ctx).read_feed(
            feed_filter or FeedFilter(),
            streams if streams is not None else _readable(world),
            before=before,
            limit=limit,
        )
    by_id = {v: k for k, v in world.ids.items()}
    return [by_id[r.id] for r in rows], rows


async def test_newest_first_across_streams_of_this_workspace_only(world):
    keys, _ = await _keys(world)
    assert keys == list(reversed(_EVENTS))


@pytest.mark.parametrize("status", list(ProcessingStatus))
async def test_the_result_filter_agrees_with_each_rows_status(world, status):
    keys, rows = await _keys(world, FeedFilter(result=status))
    assert keys == [status.value]
    assert rows[0].processing().status is status


async def test_every_status_is_what_its_routing_and_tally_say(world):
    _, rows = await _keys(world)
    by_id = {v: k for k, v in world.ids.items()}
    assert {by_id[r.id]: r.processing().status.value for r in rows} == {k: k for k in _EVENTS}


async def test_a_wildcard_kind_is_a_prefix_and_any_other_is_exact(world):
    keys, _ = await _keys(world, FeedFilter(kind="order.*"))
    assert keys == ["processing", "queued"]
    keys, _ = await _keys(world, FeedFilter(kind="order.paid"))
    assert keys == ["queued"]
    keys, _ = await _keys(world, FeedFilter(kind="order%.*"))
    assert keys == []


async def test_stream_provider_sender_and_session_filters(world):
    keys, _ = await _keys(world, FeedFilter(stream_id=world.streams["mail"].id))
    assert keys == ["error", "handled"]
    keys, _ = await _keys(world, FeedFilter(source_type="generic_webhook"))
    assert keys == ["no_handlers", "processing", "queued"]
    keys, _ = await _keys(world, FeedFilter(sender="carol"))
    assert keys == ["error", "handled"]
    keys, _ = await _keys(world, FeedFilter(session_key="s:1"))
    assert keys == ["processing", "queued"]
    keys, _ = await _keys(world, FeedFilter(event_id=world.ids["handled"]))
    assert keys == ["handled"]


async def test_since_and_until_bound_the_arrival_time(world):
    keys, _ = await _keys(
        world,
        FeedFilter(since=world.base + timedelta(minutes=1), until=world.base + timedelta(minutes=3)),
    )
    assert keys == ["handled", "processing"]


async def test_a_stream_the_caller_may_not_read_is_left_out(world):
    keys, _ = await _keys(world, streams=_readable(world, "orders", "mail"))
    assert "skipped" not in keys
    keys, _ = await _keys(world, FeedFilter(stream_id=world.streams["hidden"].id), streams=[])
    assert keys == []


async def test_pages_go_back_by_sequence(world):
    _, first = await _keys(world, limit=4)
    keys, _ = await _keys(world, before=first[-1].sequence, limit=4)
    assert keys == ["processing", "queued"]


async def test_facets_count_each_stream_and_provider_under_the_other_filters(world):
    async with world.maker() as session:
        facets = await StreamEventRepository(session, world.ctx).feed_facets(
            FeedFilter(stream_id=world.streams["mail"].id, kind="message"),
            _readable(world, "orders", "mail"),
        )
    assert facets.streams == {world.streams["mail"].id: 2}
    assert facets.source_types == {"mail": 2}
    async with world.maker() as session:
        facets = await StreamEventRepository(session, world.ctx).feed_facets(
            FeedFilter(source_type="mail"), _readable(world)
        )
    assert facets.source_types == {"generic_webhook": 3, "mail": 2, "repo": 1}
    assert facets.streams == {world.streams["mail"].id: 2}


async def test_one_event_with_its_routing(world):
    async with world.maker() as session:
        routed = await StreamEventRepository(session, world.ctx).read_routed(world.ids["error"])
    assert routed is not None
    assert (routed.subscribers, routed.reacted, routed.errors) == (3, 2, 1)


async def _record(world, key, source_type, minutes):
    stream = world.streams["orders"]
    event = StreamEvent(
        id=event_id_for(stream.id, key),
        type="task.completed",
        source="test",
        data={},
        stream_id=stream.id,
        workspace_id=world.ctx.workspace_id,
        created_by="u",
        event_key=key,
        received_at=world.base + timedelta(minutes=minutes),
        source_type=source_type,
    )
    async with world.maker() as session:
        await StreamEventRepository(session, world.ctx).record(event)
        await session.commit()
    world.ids[key] = event.id


async def test_platform_false_leaves_out_the_platforms_own_events_but_not_their_counts(world):
    await _record(world, "platform", "platform", 20)
    await _record(world, "sourceless", None, 21)
    keys, _ = await _keys(world)
    assert keys[:2] == ["sourceless", "platform"]
    keys, _ = await _keys(world, FeedFilter(platform=False))
    assert keys == ["sourceless", *reversed(_EVENTS)]
    async with world.maker() as session:
        facets = await StreamEventRepository(session, world.ctx).feed_facets(
            FeedFilter(platform=False), _readable(world)
        )
    assert facets.source_types["platform"] == 1
    assert facets.streams[world.streams["orders"].id] == 5
