"""Reactions to stream events are trigger_executions rows, one per (subscription, event).

The router records a forward's reaction (no trigger) and refines the row a
trigger's firing wrote; a redelivery finds what is recorded; another workspace
sees none of it; a forward's reaction is never listed as a trigger's firing.
Set STREAMS_TEST_DATABASE_URL.
"""

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import tenant_scoped_session_class, workspace_scope
from agentarea_common.config.database import TenantScopeMode
from agentarea_streams.domain import (
    EventFilter,
    HandlerResult,
    ReactionTally,
    StreamEvent,
    SubscriptionKind,
    SubscriptionView,
    Verdict,
)
from agentarea_streams.domain.enums import GAVE_UP_REASON
from agentarea_streams.domain.keys import event_id_for
from agentarea_triggers.domain.enums import ExecutionStatus
from agentarea_triggers.infrastructure.reaction_feed_repository import ReactionFeedRepository
from agentarea_triggers.infrastructure.reactions import (
    CausedExecutionRepository,
    ReactionRepository,
    StreamCause,
    TriggerExecutionReactionLog,
)
from agentarea_triggers.infrastructure.repository import TriggerExecutionRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")


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
    stream_id, trigger_id, trigger_sub, forward_sub = uuid4(), uuid4(), uuid4(), uuid4()
    async with raw() as session:
        await session.execute(
            text(
                "INSERT INTO streams (id, workspace_id, created_by, name, description, kind, "
                "created_at, updated_at) VALUES (:id, :ws, 'u', 'in', '', 'custom', now(), now())"
            ),
            {"id": stream_id, "ws": ctx.workspace_id},
        )
        await session.execute(
            text(
                "INSERT INTO triggers (id, workspace_id, created_by, name, description, agent_id, "
                "trigger_type, is_active, task_parameters, conditions, failure_threshold, "
                "consecutive_failures, created_at, updated_at) VALUES (:id, "
                ":ws, 'u', 't', '', :a, 'stream', true, '{}', '{}', 5, 0, now(), now())"
            ),
            {"id": trigger_id, "ws": ctx.workspace_id, "a": uuid4()},
        )
        for sub_id, kind, trig in (
            (trigger_sub, "trigger", trigger_id),
            (forward_sub, "forward", None),
        ):
            await session.execute(
                text(
                    "INSERT INTO stream_subscriptions (id, workspace_id, created_by, stream_id, "
                    "kind, trigger_id, filter, output_stream_ids, status, created_at, updated_at) "
                    "VALUES (:id, :ws, 'u', :s, :k, :t, '{}', '[]', 'active', now(), now())"
                ),
                {"id": sub_id, "ws": ctx.workspace_id, "s": stream_id, "k": kind, "t": trig},
            )
        await session.commit()

    def view(sub_id: UUID, kind: SubscriptionKind, trig: UUID | None) -> SubscriptionView:
        return SubscriptionView(
            id=sub_id,
            workspace_id=ctx.workspace_id,
            created_by="u",
            stream_id=stream_id,
            kind=kind,
            trigger_id=trig,
            filter=EventFilter(),
            output_stream_ids=[],
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    event = StreamEvent(
        id=event_id_for(stream_id, "k"),
        type="push",
        source="test",
        stream_id=stream_id,
        workspace_id=ctx.workspace_id,
        created_by="u",
        event_key="k",
        received_at=datetime.now(UTC),
        correlation_id="chain-1",
    )
    with workspace_scope(ctx.workspace_id):
        yield SimpleNamespace(
            maker=maker,
            raw=raw,
            ctx=ctx,
            event=event,
            trigger_id=trigger_id,
            trigger_view=view(trigger_sub, SubscriptionKind.TRIGGER, trigger_id),
            forward_view=view(forward_sub, SubscriptionKind.FORWARD, None),
        )
    async with raw() as session:
        for table in ("trigger_executions", "triggers", "streams"):
            await session.execute(
                text(f"DELETE FROM {table} WHERE workspace_id = :ws"),  # noqa: S608
                {"ws": ctx.workspace_id},
            )
        await session.commit()
    await engine.dispose()


async def _rows(world):
    async with world.raw() as session:
        result = await session.execute(
            text(
                "SELECT subscription_id, trigger_id, status, verdict, reason, score, task_id, "
                "derived_event_ids, correlation_id, causation_id FROM trigger_executions "
                "WHERE event_id = :e ORDER BY subscription_id"
            ),
            {"e": world.event.id},
        )
        return {row.subscription_id: row for row in result.all()}


async def test_a_forward_reaction_is_recorded_without_a_trigger(world):
    log = TriggerExecutionReactionLog()
    derived = uuid4()
    async with world.maker() as session:
        assert await log.recorded(session, world.event) == set()
        await log.record(
            session,
            world.forward_view,
            world.event,
            HandlerResult(verdict=Verdict.REACTED, derived_event_ids=[derived]),
        )
        await session.commit()
        assert await log.recorded(session, world.event) == {world.forward_view.id}
    row = (await _rows(world))[world.forward_view.id]
    assert (row.trigger_id, row.status, row.verdict) == (None, "success", "reacted")
    assert row.derived_event_ids == [str(derived)]
    assert (row.correlation_id, row.causation_id) == ("chain-1", str(world.event.id))


async def test_the_router_refines_the_row_a_firing_wrote(world):
    cause = StreamCause.of(world.trigger_view, world.event)
    async with world.maker() as session:
        firing = CausedExecutionRepository(session, world.ctx, cause)
        await firing.create(
            trigger_id=world.trigger_id,
            status=ExecutionStatus.SKIPPED.value,
            execution_time_ms=3,
            error_message="Trigger conditions not met",
            trigger_data={"n": 1},
        )
        again = await firing.create(
            trigger_id=world.trigger_id, status=ExecutionStatus.SUCCESS.value, execution_time_ms=1
        )
        assert again.status == ExecutionStatus.SKIPPED.value
        await TriggerExecutionReactionLog().record(
            session,
            world.trigger_view,
            world.event,
            HandlerResult(verdict=Verdict.SKIPPED, reason="not a refund", score=0.2),
        )
        await session.commit()
    rows = await _rows(world)
    assert len(rows) == 1
    row = rows[world.trigger_view.id]
    assert (row.trigger_id, row.status, row.verdict) == (world.trigger_id, "skipped", "skipped")
    assert (row.reason, row.score, row.task_id) == ("not a refund", 0.2, None)


async def test_another_workspace_sees_no_reaction(world):
    async with world.maker() as session:
        await TriggerExecutionReactionLog().record(
            session, world.forward_view, world.event, HandlerResult(verdict=Verdict.REACTED)
        )
        await session.commit()
    other = UserContext(user_id="u", workspace_id=str(uuid4()))
    with workspace_scope(other.workspace_id):
        async with world.maker() as session:
            reactions = ReactionRepository(session, other)
            assert await reactions.recorded_subscriptions(world.event.id) == set()
            assert await reactions.list_for_events(world.event.stream_id, [world.event.id]) == []
            assert await reactions.list_for_subscription(world.forward_view.id, 10) == []


async def test_a_forward_reaction_is_not_listed_as_a_trigger_firing(world):
    async with world.maker() as session:
        await TriggerExecutionReactionLog().record(
            session, world.forward_view, world.event, HandlerResult(verdict=Verdict.ERROR)
        )
        await session.commit()
        executions = TriggerExecutionRepository(session, world.ctx)
        assert await executions.list_executions_paginated() == []
        assert await executions.count_executions_filtered() == 0
        assert await executions.list_by_status(ExecutionStatus.FAILED) == []


async def test_the_tally_counts_every_reaction_and_a_given_up_one_as_an_error(world):
    log = TriggerExecutionReactionLog()
    async with world.maker() as session:
        assert await log.tally(session, world.event) == ReactionTally()
        await log.record(
            session,
            world.trigger_view,
            world.event,
            HandlerResult(verdict=Verdict.SKIPPED, reason="not a refund"),
        )
        await log.record(
            session,
            world.forward_view,
            world.event,
            HandlerResult(verdict=Verdict.ERROR, reason=GAVE_UP_REASON),
        )
        await session.commit()
        assert await log.tally(session, world.event) == ReactionTally(
            reacted=2, skipped=1, errors=1
        )
    other = UserContext(user_id="u", workspace_id=str(uuid4()))
    with workspace_scope(other.workspace_id):
        async with world.maker() as session:
            assert await ReactionFeedRepository(session, other).tally(world.event.id) == (
                ReactionTally()
            )
