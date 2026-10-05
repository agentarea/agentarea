"""Fan-out against the migrated schema.

One event reaches every subscription; each records its own outcome; a failing
subscriber does not hold the others back; forwards are idempotent; two
dispatchers never serve one subscription at once; cursor and outcome commit
together. The dispatcher's sessions confine every query to a workspace
(enforce mode), so a query that forgets its scope fails here.

The dispatcher serves every workspace, so assertions look only at this test's
rows; other suites' rows in the shared database may be served alongside.
Set STREAMS_TEST_DATABASE_URL.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.base.tenant_scope import tenant_scoped_session_class, workspace_scope
from agentarea_common.config.database import TenantScopeMode
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.events.ports import IntegrationEvent
from agentarea_streams.application.dispatcher import StreamDispatcher
from agentarea_streams.application.forward import ForwardHandler
from agentarea_streams.application.stream_service import StreamService
from agentarea_streams.domain import EventFilter, HandlerResult, SubscriptionKind, Verdict
from agentarea_streams.domain.ports import StreamWaker
from agentarea_streams.infrastructure.journal import StreamJournal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")
GRANT = "agentarea_common.base.workspace_scoped_repository.grant_resource_owner"


class _Waker(StreamWaker):
    def __init__(self):
        self.woken: list[UUID] = []

    async def wake(self, stream_id):
        self.woken.append(stream_id)


class _Triggers:
    """Stands in for TriggerSubscriptionHandler: reacts, or fails for chosen triggers."""

    def __init__(self, failing: set[UUID] | None = None, on_handle=None):
        self.failing = failing or set()
        self.calls: list[tuple[UUID, int]] = []
        self.on_handle = on_handle

    async def handle(self, subscription, event, session):
        if self.on_handle:
            await self.on_handle(subscription)
        self.calls.append((subscription.trigger_id, event.sequence))
        if subscription.trigger_id in self.failing:
            raise RuntimeError("downstream unavailable")
        return HandlerResult(verdict=Verdict.REACTED, task_id=uuid4())


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
    settings = EventStreamSettings()

    async def trigger_row(session) -> UUID:
        trigger_id = uuid4()
        await session.execute(
            text(
                "INSERT INTO triggers (id, workspace_id, created_by, name, description, agent_id, "
                "trigger_type, is_active, task_parameters, conditions, failure_threshold, "
                "consecutive_failures, validation_rules, created_at, updated_at) VALUES (:id, "
                ":ws, 'u', 't', '', :a, 'stream', true, '{}', '{}', 5, 0, '{}', now(), now())"
            ),
            {"id": trigger_id, "ws": ctx.workspace_id, "a": uuid4()},
        )
        return trigger_id

    with workspace_scope(ctx.workspace_id), patch(GRANT, new=AsyncMock()):
        async with maker() as session:
            service = StreamService(RepositoryFactory(session, ctx), settings)
            source = await service.create_stream(name="in", description="", retention_days=7)
            outputs = [
                await service.create_stream(name=f"out{i}", description="", retention_days=7)
                for i in range(3)
            ]
            t1, t2 = await trigger_row(session), await trigger_row(session)
            s1 = await service.subscribe_trigger(
                stream_id=source.id, trigger_id=t1, event_filter=EventFilter()
            )
            s2 = await service.subscribe_trigger(
                stream_id=source.id, trigger_id=t2, event_filter=EventFilter()
            )
            fwd = await service.create_forward(
                stream_id=source.id,
                output_stream_ids=[o.id for o in outputs],
                event_filter=EventFilter(),
            )
            await StreamJournal(session, ctx, settings).append(
                source.id,
                IntegrationEvent(type="push", source="test", data={"n": 1}),
                event_key="e1",
            )
            await session.commit()
    yield SimpleNamespace(
        maker=maker,
        raw=raw,
        ctx=ctx,
        settings=settings,
        source=source,
        outputs=outputs,
        t1=t1,
        t2=t2,
        s1=s1,
        s2=s2,
        fwd=fwd,
    )
    async with raw() as session:
        await session.execute(
            text("DELETE FROM streams WHERE workspace_id = :ws"), {"ws": ctx.workspace_id}
        )
        await session.execute(
            text("DELETE FROM triggers WHERE workspace_id = :ws"), {"ws": ctx.workspace_id}
        )
        await session.commit()
    await engine.dispose()


def _dispatcher(world, triggers, owner="d1", settings=None, waker=None, clock=None, forward=None):
    settings = settings or world.settings
    extra = {"clock": clock} if clock else {}
    return StreamDispatcher(
        session_factory=world.maker,
        settings=settings,
        handlers={
            SubscriptionKind.TRIGGER: triggers,
            SubscriptionKind.FORWARD: forward or ForwardHandler(settings),
        },
        waker=waker or _Waker(),
        owner=owner,
        **extra,
    )


def _ours(world, triggers):
    return [call for call in triggers.calls if call[0] in {world.t1, world.t2}]


async def _outcomes(world, subscription_id):
    async with world.raw() as session:
        rows = await session.execute(
            text(
                "SELECT verdict, reason, derived_sequences FROM subscription_outcomes "
                "WHERE subscription_id = :s"
            ),
            {"s": subscription_id},
        )
        return rows.all()


async def _sub(world, subscription_id):
    async with world.raw() as session:
        return (
            await session.execute(
                text(
                    "SELECT cursor_sequence, attempts, next_attempt_at, last_error, lease_owner, "
                    "leased_until FROM stream_subscriptions WHERE id = :s"
                ),
                {"s": subscription_id},
            )
        ).one()


async def _derived(world):
    async with world.raw() as session:
        rows = await session.execute(
            text("SELECT causation_id, depth FROM stream_events WHERE stream_id = ANY(:ids)"),
            {"ids": [o.id for o in world.outputs]},
        )
        return rows.all()


async def test_one_event_reaches_two_triggers_and_a_forward_into_three_streams(world):
    waker = _Waker()
    await _dispatcher(world, _Triggers(), waker=waker).run_once()
    for sub in (world.s1, world.s2):
        assert [o.verdict for o in await _outcomes(world, sub.id)] == ["reacted"]
    (forward,) = await _outcomes(world, world.fwd.id)
    assert forward.verdict == "reacted" and len(forward.derived_sequences) == 3
    derived = await _derived(world)
    assert len(derived) == 3 and {d.depth for d in derived} == {1}
    assert {o.id for o in world.outputs} <= set(waker.woken)
    for sub in (world.s1, world.s2, world.fwd):
        assert (await _sub(world, sub.id)).lease_owner is None


async def test_a_failing_subscriber_does_not_block_the_others(world):
    await _dispatcher(world, _Triggers(failing={world.t1})).run_once()
    failed, ok = await _sub(world, world.s1.id), await _sub(world, world.s2.id)
    assert failed.attempts == 1 and failed.next_attempt_at is not None
    assert failed.last_error == "downstream unavailable"
    assert failed.lease_owner is None and failed.leased_until is None
    assert await _outcomes(world, world.s1.id) == []
    assert [o.verdict for o in await _outcomes(world, world.s2.id)] == ["reacted"]
    assert ok.cursor_sequence > failed.cursor_sequence


async def test_a_subscriber_failing_every_attempt_gets_an_error_outcome_and_moves_on(world):
    settings = EventStreamSettings(MAX_ATTEMPTS=2)
    triggers = _Triggers(failing={world.t1})
    await _dispatcher(world, triggers, settings=settings).run_once()
    assert (await _sub(world, world.s1.id)).attempts == 1

    def later():
        return datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)

    await _dispatcher(world, triggers, settings=settings, clock=later).run_once()
    gave_up = await _sub(world, world.s1.id)
    assert [(o.verdict, o.reason) for o in await _outcomes(world, world.s1.id)] == [
        ("error", "gave up: downstream unavailable")
    ]
    assert gave_up.cursor_sequence > world.s1.cursor_sequence
    assert gave_up.attempts == 0 and gave_up.next_attempt_at is None
    assert len([c for c in _ours(world, triggers) if c[0] == world.t1]) == 2


async def test_a_forward_over_the_write_quota_retries_later_instead_of_dropping(world):
    over_quota = ForwardHandler(EventStreamSettings(WRITE_QUOTA=1))
    await _dispatcher(world, _Triggers(), forward=over_quota).run_once()
    held = await _sub(world, world.fwd.id)
    assert held.attempts == 1 and held.next_attempt_at is not None
    assert "exceeded 1 events per minute" in held.last_error
    assert held.cursor_sequence == world.fwd.cursor_sequence
    assert await _outcomes(world, world.fwd.id) == []
    assert await _derived(world) == []


async def test_replaying_a_forward_does_not_duplicate_events(world):
    await _dispatcher(world, _Triggers()).run_once()
    async with world.raw() as session:
        await session.execute(
            text("UPDATE stream_subscriptions SET cursor_sequence = 0 WHERE id = :s"),
            {"s": world.fwd.id},
        )
        await session.execute(
            text("DELETE FROM subscription_outcomes WHERE subscription_id = :s"),
            {"s": world.fwd.id},
        )
        await session.commit()
    await _dispatcher(world, _Triggers()).run_once()
    assert len(await _derived(world)) == 3
    (forward,) = await _outcomes(world, world.fwd.id)
    assert forward.verdict == "reacted" and len(forward.derived_sequences) == 3


async def test_two_dispatchers_never_serve_one_subscription_twice(world):
    triggers = _Triggers()
    await asyncio.gather(
        _dispatcher(world, triggers, owner="a").run_once(),
        _dispatcher(world, triggers, owner="b").run_once(),
    )
    ours = _ours(world, triggers)
    assert len(ours) == 2
    assert {trigger for trigger, _ in ours} == {world.t1, world.t2}
    assert len(await _derived(world)) == 3


async def test_cursor_and_outcome_commit_together_or_not_at_all(world):
    async def steal_lease(subscription):
        async with world.raw() as session:
            await session.execute(
                text("UPDATE stream_subscriptions SET lease_owner = 'thief' WHERE id = :s"),
                {"s": subscription.id},
            )
            await session.commit()

    await _dispatcher(world, _Triggers(on_handle=steal_lease)).run_once()
    sub = await _sub(world, world.s1.id)
    assert await _outcomes(world, world.s1.id) == []
    assert sub.cursor_sequence == world.s1.cursor_sequence
    assert sub.lease_owner == "thief"


async def test_events_outside_the_filter_move_the_cursor_without_an_outcome(world):
    async with world.raw() as session:
        await session.execute(
            text("UPDATE stream_subscriptions SET filter = :f WHERE id = :s"),
            {"f": '{"kinds": ["issue"], "fields": {}}', "s": world.s1.id},
        )
        await session.commit()
    triggers = _Triggers()
    await _dispatcher(world, triggers).run_once()
    assert await _outcomes(world, world.s1.id) == []
    assert (await _sub(world, world.s1.id)).cursor_sequence > world.s1.cursor_sequence
    assert world.t1 not in {trigger for trigger, _ in triggers.calls}
