"""The router group against the migrated schema (ADR-0043 §3).

One bus event reaches every matching subscription of its stream; each reaction
is recorded before the ack; a redelivery runs only what is not recorded; one
failing subscription does not hold back the others; past the delivery limit the
rest are recorded as errors; a stale cache never fires a deleted or paused
subscription. Sessions confine every query to a workspace (enforce mode).
Set STREAMS_TEST_DATABASE_URL.
"""

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.base.tenant_scope import tenant_scoped_session_class, workspace_scope
from agentarea_common.config.database import TenantScopeMode
from agentarea_common.config.streams import EventStreamSettings
from agentarea_streams.application.events_view import EventsView
from agentarea_streams.application.forward import ForwardHandler
from agentarea_streams.application.router import EventRouter, ReactionsFailedError
from agentarea_streams.application.stream_service import StreamService
from agentarea_streams.domain import (
    EventFilter,
    HandlerResult,
    ReactionTally,
    StreamEvent,
    SubscriptionKind,
    Verdict,
)
from agentarea_common.events.ports import IntegrationEvent, UnprocessableEventError
from agentarea_streams.domain.enums import GAVE_UP_REASON
from agentarea_streams.infrastructure.orm import StreamSubscriptionORM
from agentarea_streams.domain.keys import derived_event_id, event_id_for
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")
GRANT = "agentarea_common.base.workspace_scoped_repository.grant_resource_owner"


class _Reactions:
    """An in-memory ReactionLog: one result per (subscription, event)."""

    def __init__(self):
        self.rows: dict[tuple[UUID, UUID], HandlerResult] = {}

    async def recorded(self, session, event):
        return {
            sub
            for (sub, event_id), result in self.rows.items()
            if event_id == event.id and result.reason != GAVE_UP_REASON
        }

    async def record(self, session, subscription, event, result):
        self.rows[(subscription.id, event.id)] = result

    async def forget_given_up(self, session, subscription, event):
        key = (subscription.id, event.id)
        if key in self.rows and self.rows[key].reason == GAVE_UP_REASON:
            del self.rows[key]

    async def tally(self, session, event):
        verdicts = [r.verdict for (_, e), r in self.rows.items() if e == event.id]
        return ReactionTally(
            reacted=len(verdicts),
            skipped=verdicts.count(Verdict.SKIPPED),
            errors=verdicts.count(Verdict.ERROR),
        )


class _Triggers:
    def __init__(self, failing: set[UUID] | None = None):
        self.failing = failing or set()
        self.calls: list[UUID] = []

    async def handle(self, subscription, event, session):
        self.calls.append(subscription.trigger_id)
        if subscription.trigger_id in self.failing:
            raise RuntimeError("downstream unavailable")
        return HandlerResult(verdict=Verdict.REACTED, task_id=uuid4())


class _Notices:
    def __init__(self):
        self.sent: list[tuple[str, UUID]] = []

    async def recorded(self, event):
        self.sent.append(("recorded", event.id))

    async def processing(self, event):
        self.sent.append(("processing", event.id))


class _Quota:
    async def take(self, workspace_id, limit, now):
        return True


class _Bus:
    def __init__(self):
        self.published: list[StreamEvent] = []
        self.quota = _Quota()

    async def publish(self, event):
        if any(e.id == event.id for e in self.published):
            return False
        self.published.append(event)
        return True


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

    async def trigger_row(session) -> UUID:
        trigger_id = uuid4()
        await session.execute(
            text(
                "INSERT INTO triggers (id, workspace_id, created_by, name, description, agent_id, "
                "trigger_type, is_active, task_parameters, conditions, failure_threshold, "
                "consecutive_failures, created_at, updated_at) VALUES (:id, "
                ":ws, 'u', 't', '', :a, 'stream', true, '{}', '{}', 5, 0, now(), now())"
            ),
            {"id": trigger_id, "ws": ctx.workspace_id, "a": uuid4()},
        )
        return trigger_id

    with workspace_scope(ctx.workspace_id), patch(GRANT, new=AsyncMock()):
        async with maker() as session:
            service = StreamService(RepositoryFactory(session, ctx), EventStreamSettings())
            source = await service.create_stream(name="in", description="")
            outputs = [
                await service.create_stream(name=f"out{i}", description="") for i in range(2)
            ]
            t1, t2, t3 = [await trigger_row(session) for _ in range(3)]
            s1 = await service.subscribe_trigger(
                stream_id=source.id, trigger_id=t1, event_filter=EventFilter()
            )
            s2 = await service.subscribe_trigger(
                stream_id=source.id, trigger_id=t2, event_filter=EventFilter()
            )
            s3 = await service.subscribe_trigger(
                stream_id=source.id, trigger_id=t3, event_filter=EventFilter(kinds=["issue"])
            )
            fwd = await service.create_forward(
                stream_id=source.id,
                output_stream_ids=[o.id for o in outputs],
                event_filter=EventFilter(),
            )
            await session.commit()

    async def subscribe_new_trigger() -> tuple[UUID, UUID]:
        with workspace_scope(ctx.workspace_id), patch(GRANT, new=AsyncMock()):
            async with maker() as session:
                trigger_id = await trigger_row(session)
                sub = await StreamService(
                    RepositoryFactory(session, ctx), EventStreamSettings()
                ).subscribe_trigger(
                    stream_id=source.id, trigger_id=trigger_id, event_filter=EventFilter()
                )
                await session.commit()
        return trigger_id, sub.id

    yield SimpleNamespace(
        subscribe_new_trigger=subscribe_new_trigger,
        maker=maker,
        raw=raw,
        ctx=ctx,
        source=source,
        outputs=outputs,
        t1=t1,
        t2=t2,
        t3=t3,
        s1=s1,
        s2=s2,
        s3=s3,
        fwd=fwd,
    )
    async with raw() as session:
        for table in ("streams", "triggers", "event_outbox"):
            await session.execute(
                text(f"DELETE FROM {table} WHERE workspace_id = :ws"),  # noqa: S608
                {"ws": ctx.workspace_id},
            )
        await session.commit()
    await engine.dispose()


def _event(world, *, kind="push", depth=0, key="e1", received_at=None) -> StreamEvent:
    return StreamEvent(
        id=event_id_for(world.source.id, key),
        type=kind,
        source="test",
        data={"n": 1},
        stream_id=world.source.id,
        workspace_id=world.ctx.workspace_id,
        created_by="u",
        event_key=key,
        received_at=received_at or datetime.now(UTC),
        depth=depth,
    )


def _router(world, triggers, reactions, bus=None, notices=None, **kwargs):
    return EventRouter(
        session_factory=world.maker,
        handlers={
            SubscriptionKind.TRIGGER: triggers,
            SubscriptionKind.FORWARD: ForwardHandler(EventStreamSettings(), bus or _Bus()),
            SubscriptionKind.EXTERNAL: _Triggers(),
            SubscriptionKind.PROCESSOR: _Triggers(),
        },
        reactions=reactions,
        notices=notices or _Notices(),
        **kwargs,
    )


async def _routing(world, event_id) -> tuple[datetime | None, int | None, int]:
    async with world.raw() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT routed_at, subscribers, data FROM stream_events "
                    "WHERE event_id = :e AND workspace_id = :ws"
                ),
                {"e": event_id, "ws": world.ctx.workspace_id},
            )
        ).all()
    assert all(row[2] == {"n": 1} for row in rows)
    if not rows:
        return None, None, 0
    return rows[0][0], rows[0][1], len(rows)


async def test_one_event_reaches_every_matching_subscription_and_each_is_recorded(world):
    triggers, reactions, bus = _Triggers(), _Reactions(), _Bus()
    event = _event(world)
    await _router(world, triggers, reactions, bus).handle(event.to_bus())
    assert sorted(triggers.calls) == sorted([world.t1, world.t2])
    assert set(reactions.rows) == {(s.id, event.id) for s in (world.s1, world.s2, world.fwd)}
    forwarded = reactions.rows[(world.fwd.id, event.id)]
    assert forwarded.verdict is Verdict.REACTED
    assert sorted(e.stream_id for e in bus.published) == sorted(o.id for o in world.outputs)
    assert [e.id for e in bus.published] == forwarded.derived_event_ids
    copy = derived_event_id(world.fwd.id, event.id)
    assert {e.id for e in bus.published} == {derived_event_id(copy, o.id) for o in world.outputs}
    assert all(e.causation_id == str(event.id) and e.depth == 1 for e in bus.published)


async def test_a_redelivered_event_runs_only_the_reactions_not_recorded(world):
    triggers, reactions = _Triggers(failing={world.t2}), _Reactions()
    router = _router(world, triggers, reactions)
    event = _event(world)
    with pytest.raises(ReactionsFailedError):
        await router.handle(event.to_bus())
    assert (world.s2.id, event.id) not in reactions.rows
    assert {world.s1.id, world.fwd.id} <= {sub for sub, _ in reactions.rows}

    triggers.failing.clear()
    triggers.calls.clear()
    await router.handle(event.to_bus())
    assert triggers.calls == [world.t2]
    assert (world.s2.id, event.id) in reactions.rows


async def test_past_the_delivery_limit_the_rest_are_recorded_as_errors(world):
    triggers, reactions = _Triggers(failing={world.t1}), _Reactions()
    router = _router(world, triggers, reactions)
    event = _event(world)
    with pytest.raises(ReactionsFailedError):
        await router.handle(event.to_bus())
    await router.give_up(event.to_bus())
    gave_up = reactions.rows[(world.s1.id, event.id)]
    assert gave_up.verdict is Verdict.ERROR
    assert "delivery limit" in (gave_up.reason or "")
    assert reactions.rows[(world.s2.id, event.id)].verdict is Verdict.REACTED


async def test_a_replayed_dead_letter_runs_the_given_up_reactions_again(world):
    triggers, reactions = _Triggers(failing={world.t1}), _Reactions()
    router = _router(world, triggers, reactions)
    event = _event(world)
    with pytest.raises(ReactionsFailedError):
        await router.handle(event.to_bus())
    await router.give_up(event.to_bus())

    triggers.failing.clear()
    triggers.calls.clear()
    await router.handle(event.to_bus())
    assert triggers.calls == [world.t1]
    assert reactions.rows[(world.s1.id, event.id)].verdict is Verdict.REACTED


async def test_a_message_that_is_no_stream_event_is_unprocessable(world):
    router = _router(world, _Triggers(), _Reactions())
    message = IntegrationEvent(type="push", source="test", data={"n": 1})
    with pytest.raises(UnprocessableEventError):
        await router.handle(message)
    with pytest.raises(UnprocessableEventError):
        await router.give_up(message)


async def test_a_stale_cache_never_fires_a_deleted_or_paused_subscription(world):
    triggers, reactions = _Triggers(), _Reactions()
    router = _router(world, triggers, reactions)
    await router.handle(_event(world, key="warm").to_bus())
    async with world.raw() as session:
        await session.execute(
            text("DELETE FROM stream_subscriptions WHERE id = :s"), {"s": world.s1.id}
        )
        await session.execute(
            text("UPDATE stream_subscriptions SET status = 'paused' WHERE id = :s"),
            {"s": world.s2.id},
        )
        await session.commit()
    triggers.calls.clear()
    event = _event(world, key="after")
    await router.handle(event.to_bus())
    assert triggers.calls == []
    assert (world.s1.id, event.id) not in reactions.rows
    assert (world.s2.id, event.id) not in reactions.rows


async def test_a_new_subscription_is_seen_once_its_stream_is_invalidated(world):
    triggers, reactions = _Triggers(), _Reactions()
    router = _router(world, triggers, reactions, cache_ttl_s=3600)
    earlier = datetime.now(UTC)
    await router.handle(_event(world, kind="issue", key="first").to_bus())
    assert triggers.calls.count(world.t3) == 1
    async with world.raw() as session:
        await session.execute(
            text("UPDATE stream_subscriptions SET filter = :f WHERE id = :s"),
            {"f": '{"kinds": ["nothing"], "fields": {}}', "s": world.s3.id},
        )
        await session.commit()
    triggers.calls.clear()
    # Received before the cache was read: served from it.
    await router.handle(_event(world, kind="issue", key="cached", received_at=earlier).to_bus())
    assert world.t3 in triggers.calls
    router.invalidate(world.source.id)
    triggers.calls.clear()
    await router.handle(_event(world, kind="issue", key="fresh").to_bus())
    assert world.t3 not in triggers.calls


async def test_a_forward_past_the_causation_depth_is_an_error_and_writes_nothing(world):
    triggers, reactions, bus = _Triggers(), _Reactions(), _Bus()
    event = _event(world, depth=EventStreamSettings().FORWARD_DEPTH)
    await _router(world, triggers, reactions, bus).handle(event.to_bus())
    result = reactions.rows[(world.fwd.id, event.id)]
    assert result.verdict is Verdict.ERROR
    assert "causation depth" in (result.reason or "")
    assert bus.published == []


async def test_an_event_carried_back_over_mcp_events_at_the_limit_is_not_forwarded_again(world):
    """Stream A -> our own MCP Events -> this stream -> forward -> A: the hop keeps the depth."""
    import json
    from pathlib import Path

    from agentarea_streams.application.source_intake import SourceIntake
    from agentarea_streams.domain.mcp_events import occurrence
    from agentarea_streams.domain.source_types import SourceTypeEntry

    catalog = Path(__file__).parents[4] / "data" / "catalog" / "source-types.json"
    entry = SourceTypeEntry.model_validate(
        next(
            e for e in json.loads(catalog.read_text())["source_types"] if e["slug"] == "mcp_events"
        )
    )
    limit = EventStreamSettings().FORWARD_DEPTH
    elsewhere = _event(world, depth=limit - 1, key="in-stream-a").model_copy(
        update={"correlation_id": str(uuid4())}
    )
    source = SimpleNamespace(
        id=uuid4(),
        stream_id=world.source.id,
        workspace_id=world.ctx.workspace_id,
        created_by="u",
        event_templates=None,
        webhook_config=None,
    )
    intake_bus = _Bus()
    async with world.maker() as session:
        with workspace_scope(world.ctx.workspace_id):
            await SourceIntake(
                bus=intake_bus, files=object(), settings=EventStreamSettings()
            ).ingest(
                session,
                source,
                entry,
                body=json.loads(json.dumps(occurrence(elsewhere, "ws/a"))),
                headers={},
                received_at=datetime.now(UTC),
            )
    (carried,) = intake_bus.published
    assert carried.depth == limit
    assert (carried.causation_id, carried.correlation_id) == (
        str(elsewhere.id),
        elsewhere.correlation_id,
    )

    triggers, reactions, bus = _Triggers(), _Reactions(), _Bus()
    await _router(world, triggers, reactions, bus).handle(carried.to_bus())
    result = reactions.rows[(world.fwd.id, carried.id)]
    assert result.verdict is Verdict.ERROR
    assert result.reason == f"causation depth {limit + 1} exceeds {limit}"
    assert bus.published == []


async def test_subscription_changes_are_announced_on_the_domain_path(world):
    async with world.raw() as session:
        rows = await session.execute(
            text(
                "SELECT payload->'data'->>'stream_id' FROM event_outbox "
                "WHERE workspace_id = :ws AND event_type = 'streams.subscriptions.changed'"
            ),
            {"ws": world.ctx.workspace_id},
        )
        announced = [r[0] for r in rows.all()]
    assert announced.count(str(world.source.id)) == 4


async def test_a_forward_skips_an_output_deleted_since_it_was_read(world):
    from agentarea_streams.application.router import subscription_view

    bus = _Bus()
    event = _event(world)
    async with world.maker() as session:
        with workspace_scope(world.ctx.workspace_id):
            view = subscription_view(await session.get(StreamSubscriptionORM, world.fwd.id))
            gone = uuid4()
            view = view.model_copy(update={"output_stream_ids": [*view.output_stream_ids, gone]})
            result = await ForwardHandler(EventStreamSettings(), bus).handle(view, event, session)

    assert result.verdict is Verdict.REACTED
    assert sorted(e.stream_id for e in bus.published) == sorted(o.id for o in world.outputs)
    assert len(result.derived_event_ids) == len(world.outputs)


async def test_a_subscription_created_after_the_cache_was_read_gets_the_next_event(world):
    triggers, reactions = _Triggers(), _Reactions()
    router = _router(world, triggers, reactions, cache_ttl_s=3600)
    await router.handle(_event(world, kind="issue", key="first").to_bus())
    async with world.raw() as session:
        await session.execute(
            text("UPDATE stream_subscriptions SET filter = :f WHERE id = :s"),
            {"f": '{"kinds": ["nothing"], "fields": {}}', "s": world.s3.id},
        )
        await session.commit()
    triggers.calls.clear()

    # No change notice has arrived; the event came after the cache was read.
    await router.handle(_event(world, kind="issue", key="after").to_bus())

    assert world.t3 not in triggers.calls


async def test_the_router_writes_when_it_routed_an_event_and_to_how_many(world):
    notices = _Notices()
    event = _event(world)
    await _router(world, _Triggers(), _Reactions(), notices=notices).handle(event.to_bus())
    routed_at, subscribers, rows = await _routing(world, event.id)
    assert routed_at is not None
    assert subscribers == 3
    assert rows == 1
    # The events view has not written it yet: the router's write is the first.
    assert notices.sent[0] == ("recorded", event.id)
    assert notices.sent[1:] == [("processing", event.id)] * 3


async def test_an_event_nobody_subscribes_to_is_routed_to_no_one(world):
    notices = _Notices()
    event = _event(world).model_copy(update={"stream_id": world.outputs[0].id})
    await _router(world, _Triggers(), _Reactions(), notices=notices).handle(event.to_bus())
    routed_at, subscribers, _ = await _routing(world, event.id)
    assert routed_at is not None
    assert subscribers == 0
    assert notices.sent == [("recorded", event.id)]


async def test_a_redelivery_keeps_the_first_routing(world):
    triggers, reactions = _Triggers(failing={world.t2}), _Reactions()
    router = _router(world, triggers, reactions)
    event = _event(world)
    with pytest.raises(ReactionsFailedError):
        await router.handle(event.to_bus())
    first = await _routing(world, event.id)

    triggers.failing.clear()
    await router.handle(event.to_bus())
    assert await _routing(world, event.id) == first
    assert first[1] == 3


async def test_the_router_and_the_events_view_write_one_row_whichever_is_first(world):
    notices = _Notices()
    router = _router(world, _Triggers(), _Reactions(), notices=notices)
    view = EventsView(world.maker, notices)

    routed_first = _event(world, key="routed-first")
    await router.handle(routed_first.to_bus())
    await view.handle(routed_first.to_bus())
    viewed_first = _event(world, key="viewed-first")
    await view.handle(viewed_first.to_bus())
    await router.handle(viewed_first.to_bus())

    for event in (routed_first, viewed_first):
        routed_at, subscribers, rows = await _routing(world, event.id)
        assert (routed_at is not None, subscribers, rows) == (True, 3, 1)
    assert notices.sent.count(("processing", viewed_first.id)) == 4
    assert notices.sent.count(("recorded", viewed_first.id)) == 1


async def test_a_subscription_gone_before_it_reacted_is_not_counted(world):
    triggers, reactions = _Triggers(), _Reactions()
    router = _router(world, triggers, reactions, cache_ttl_s=3600)
    earlier = datetime.now(UTC)
    await router.handle(_event(world, key="warm").to_bus())
    async with world.raw() as session:
        await session.execute(
            text("DELETE FROM stream_subscriptions WHERE id = :s"), {"s": world.s1.id}
        )
        await session.execute(
            text("UPDATE stream_subscriptions SET status = 'paused' WHERE id = :s"),
            {"s": world.s2.id},
        )
        await session.commit()
    # Received before the cache was read: the cache still names both.
    event = _event(world, key="stale", received_at=earlier)
    await router.handle(event.to_bus())
    _, subscribers, _ = await _routing(world, event.id)
    assert subscribers == 1


async def test_each_reaction_updates_the_tally_on_the_event(world):
    triggers, reactions = _Triggers(failing={world.t1}), _Reactions()
    router = _router(world, triggers, reactions)
    event = _event(world)
    with pytest.raises(ReactionsFailedError):
        await router.handle(event.to_bus())
    assert await _tally(world, event.id) == (2, 0, 0)
    await router.give_up(event.to_bus())
    assert await _tally(world, event.id) == (3, 0, 1)


async def _tally(world, event_id) -> tuple[int, int, int]:
    async with world.raw() as session:
        row = (
            await session.execute(
                text(
                    "SELECT reacted, skipped, errors FROM stream_events "
                    "WHERE event_id = :e AND workspace_id = :ws"
                ),
                {"e": event_id, "ws": world.ctx.workspace_id},
            )
        ).one()
    return row[0], row[1], row[2]


async def test_a_subscription_never_fires_on_an_event_received_before_it_started(world):
    triggers, reactions = _Triggers(failing={world.t2}), _Reactions()
    router = _router(world, triggers, reactions)
    event = _event(world)
    with pytest.raises(ReactionsFailedError):
        await router.handle(event.to_bus())
    late_trigger, late_sub = await world.subscribe_new_trigger()
    router.invalidate(world.source.id)

    triggers.failing.clear()
    triggers.calls.clear()
    await router.handle(event.to_bus())

    assert triggers.calls == [world.t2]
    skipped = reactions.rows[(late_sub, event.id)]
    assert skipped.verdict is Verdict.SKIPPED
    assert skipped.reason == "received before the subscription started"
    assert late_trigger not in triggers.calls
    assert await _tally(world, event.id) == (4, 1, 0)
