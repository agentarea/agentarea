"""Batched reactions on a real schema: held while the batch is open, settled with its one task.

The feed reads each event's tally, so a held event shows processing, a fired
batch shows every event handled by the same task, and a batch closed by
switching the trigger off shows its events skipped, also after the trigger and
its reactions are deleted. Set STREAMS_TEST_DATABASE_URL.
"""

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import tenant_scoped_session_class, workspace_scope
from agentarea_common.config.database import TenantScopeMode
from agentarea_execution.workflows.trigger_batch_workflow import BatchSpec, OpenBatch
from agentarea_streams.domain import (
    EventFilter,
    HandlerResult,
    StreamEvent,
    SubscriptionKind,
    SubscriptionView,
    Verdict,
)
from agentarea_streams.domain.keys import event_id_for
from agentarea_streams.domain.processing import ProcessingStatus
from agentarea_streams.infrastructure.event_repository import StreamEventRepository
from agentarea_triggers.batch_firing import TriggerBatchFirer, close_open_batches, retally
from agentarea_triggers.batches import batch_task_id
from agentarea_triggers.domain.models import StreamTrigger, TriggerBatchWindow, TriggerFiring
from agentarea_triggers.infrastructure.reactions import TriggerExecutionReactionLog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")

WORKFLOW = "trigger-batch-test"


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
    stream_id, trigger_id, sub_id = uuid4(), uuid4(), uuid4()
    async with raw() as session:
        await session.execute(
            text(
                "INSERT INTO streams (id, workspace_id, created_by, name, description, kind, "
                "created_at, updated_at) VALUES (:id, :ws, 'u', 'orders', '', 'custom', now(), "
                "now())"
            ),
            {"id": stream_id, "ws": ctx.workspace_id},
        )
        await session.execute(
            text(
                "INSERT INTO triggers (id, workspace_id, created_by, name, description, agent_id, "
                "trigger_type, is_active, task_parameters, conditions, failure_threshold, "
                "consecutive_failures, batch, created_at, updated_at) VALUES (:id, :ws, 'u', "
                "'digest', '', :a, 'stream', true, '{\"text\": \"Summarise\"}', '{}', 5, 0, "
                "'{\"window\": \"60s\", \"max_events\": 3}', now(), now())"
            ),
            {"id": trigger_id, "ws": ctx.workspace_id, "a": uuid4()},
        )
        await session.execute(
            text(
                "INSERT INTO stream_subscriptions (id, workspace_id, created_by, stream_id, "
                "kind, trigger_id, filter, output_stream_ids, status, created_at, updated_at) "
                "VALUES (:id, :ws, 'u', :s, 'trigger', :t, '{}', '[]', 'active', now(), now())"
            ),
            {"id": sub_id, "ws": ctx.workspace_id, "s": stream_id, "t": trigger_id},
        )
        await session.commit()

    view = SubscriptionView(
        id=sub_id,
        workspace_id=ctx.workspace_id,
        created_by="u",
        stream_id=stream_id,
        kind=SubscriptionKind.TRIGGER,
        trigger_id=trigger_id,
        filter=EventFilter(),
        output_stream_ids=[],
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    now = datetime.now(UTC)
    events = [
        StreamEvent(
            id=event_id_for(stream_id, key),
            type="order.paid",
            source="test",
            data={"body": {"order": key}},
            stream_id=stream_id,
            workspace_id=ctx.workspace_id,
            created_by="u",
            event_key=key,
            received_at=now + timedelta(milliseconds=n),
            correlation_id=f"chain-{key}",
        )
        for n, key in enumerate(("a", "b", "c"))
    ]
    with workspace_scope(ctx.workspace_id):
        async with maker() as session:
            repository = StreamEventRepository(session, ctx)
            for event in events:
                await repository.mark_routed(event, 1, at=now)
            await session.commit()
        yield SimpleNamespace(
            maker=maker,
            raw=raw,
            ctx=ctx,
            events=events,
            view=view,
            trigger_id=trigger_id,
            spec=BatchSpec(
                trigger_id=trigger_id,
                subscription_id=sub_id,
                workspace_id=ctx.workspace_id,
                configured_by="u",
                window_seconds=60.0,
                max_events=3,
            ),
        )
    async with raw() as session:
        for table in ("trigger_executions", "stream_events", "triggers", "streams"):
            await session.execute(
                text(f"DELETE FROM {table} WHERE workspace_id = :ws"),  # noqa: S608
                {"ws": ctx.workspace_id},
            )
        await session.commit()
    await engine.dispose()


async def _hold(world, event: StreamEvent) -> None:
    """What the router records when the trigger handler hands an event to a batch."""
    async with world.maker() as session:
        log = TriggerExecutionReactionLog()
        await log.record(
            session,
            world.view,
            event,
            HandlerResult(verdict=Verdict.BATCHED, reason="held", workflow_id=WORKFLOW),
        )
        await retally(session, world.ctx, event)
        await session.commit()


async def _status(world, event: StreamEvent) -> ProcessingStatus:
    async with world.maker() as session:
        routed = await StreamEventRepository(session, world.ctx).read_routed(event.id)
    assert routed is not None
    return routed.processing().status


async def _rows(world) -> dict[UUID, SimpleNamespace]:
    async with world.raw() as session:
        result = await session.execute(
            text(
                "SELECT event_id, status, verdict, reason, task_id, workflow_id "
                "FROM trigger_executions WHERE workspace_id = :ws"
            ),
            {"ws": world.ctx.workspace_id},
        )
        return {row.event_id: row for row in result.all()}


class _Service:
    def __init__(self, trigger: StreamTrigger | None, task_id: UUID | None = None):
        self.trigger = trigger
        self.stream_service = SimpleNamespace(
            get_stream=AsyncMock(return_value=SimpleNamespace(name="orders"))
        )
        self.fire = AsyncMock(
            return_value=TriggerFiring(outcome="reacted", task_id=task_id or uuid4())
        )
        self.trigger_execution_repository = None

    async def get_trigger(self, _trigger_id):
        return self.trigger


def _trigger(world, *, is_active: bool = True) -> StreamTrigger:
    return StreamTrigger(
        id=world.trigger_id,
        name="digest",
        agent_id=uuid4(),
        created_by="u",
        workspace_id=world.ctx.workspace_id,
        is_active=is_active,
        task_parameters={"text": "Summarise"},
        batch=TriggerBatchWindow(window="60s", max_events=3),
    )


def _firer(world, service: _Service, notices=None) -> TriggerBatchFirer:
    return TriggerBatchFirer(
        session_factory=world.maker,
        trigger_service_factory=lambda _session, _context: service,
        notices=notices or AsyncMock(),
    )


def _batch(world, events, reason=None) -> OpenBatch:
    return OpenBatch(
        spec=world.spec, workflow_id=WORKFLOW, event_ids=[e.id for e in events], reason=reason
    )


async def test_a_held_event_is_processing_and_its_reaction_counts_as_recorded(world):
    event = world.events[0]
    await _hold(world, event)
    assert await _status(world, event) is ProcessingStatus.PROCESSING
    async with world.maker() as session:
        assert await TriggerExecutionReactionLog().recorded(session, event) == {world.view.id}
    row = (await _rows(world))[event.id]
    assert (row.status, row.verdict, row.workflow_id) == ("batched", "batched", WORKFLOW)


async def test_a_fired_batch_settles_every_event_with_its_one_task(world):
    first, second = world.events[:2]
    await _hold(world, first)
    await _hold(world, second)
    task = uuid4()
    service = _Service(_trigger(world), task)
    notices = AsyncMock()
    assert await _firer(world, service, notices).fire(_batch(world, [first, second])) == 2

    args, kwargs = service.fire.await_args
    told = kwargs["event"]
    assert [e["key"] for e in told.data["events"]] == ["a", "b"]
    assert told.data == args[1]
    assert told.stream_name == "orders"
    assert kwargs["task_id"] == batch_task_id(world.view.id, first.id)
    assert kwargs["evaluate_conditions"] is False
    assert kwargs["provenance"].causation_id == str(second.id)
    assert kwargs["delivery"].session is None
    rows = await _rows(world)
    for event in (first, second):
        assert (rows[event.id].verdict, rows[event.id].task_id) == ("reacted", task)
        assert rows[event.id].workflow_id == WORKFLOW
        assert await _status(world, event) is ProcessingStatus.HANDLED
    assert [c.args[0].id for c in notices.processing.await_args_list] == [first.id, second.id]


async def test_the_batch_may_fire_before_the_router_records_the_event(world):
    event = world.events[0]
    task = uuid4()
    await _firer(world, _Service(_trigger(world), task)).fire(_batch(world, [event]))
    await _hold(world, event)
    row = (await _rows(world))[event.id]
    assert (row.verdict, row.task_id) == ("reacted", task)
    assert await _status(world, event) is ProcessingStatus.HANDLED


async def test_an_event_settled_by_an_earlier_batch_is_left_out(world):
    first, second = world.events[:2]
    await _hold(world, first)
    earlier = uuid4()
    await _firer(world, _Service(_trigger(world), earlier)).fire(_batch(world, [first]))
    await _hold(world, second)
    service = _Service(_trigger(world))
    assert await _firer(world, service).fire(_batch(world, [first, second])) == 1
    told = service.fire.await_args.kwargs["event"]
    assert [e["key"] for e in told.data["events"]] == ["b"]
    assert (await _rows(world))[first.id].task_id == earlier


async def test_a_trigger_switched_off_before_the_batch_fires_starts_no_task(world):
    event = world.events[0]
    await _hold(world, event)
    service = _Service(_trigger(world, is_active=False))
    await _firer(world, service).fire(_batch(world, [event]))
    service.fire.assert_not_awaited()
    row = (await _rows(world))[event.id]
    assert (row.verdict, row.reason, row.task_id) == ("skipped", "trigger is inactive", None)
    assert await _status(world, event) is ProcessingStatus.SKIPPED


async def test_a_cancelled_batch_closes_its_events_as_skipped(world):
    event = world.events[0]
    await _hold(world, event)
    service = _Service(_trigger(world))
    await _firer(world, service).close(_batch(world, [event], reason="cancelled"))
    service.fire.assert_not_awaited()
    row = (await _rows(world))[event.id]
    assert (row.verdict, row.reason) == ("skipped", "cancelled")


async def test_closing_a_trigger_skips_its_held_events_and_the_tally_outlives_the_delete(world):
    first, second = world.events[:2]
    await _hold(world, first)
    await _hold(world, second)
    async with world.maker() as session:
        closed = await close_open_batches(session, world.ctx, world.trigger_id, "trigger deleted")
        await session.commit()
    assert closed == [WORKFLOW]
    rows = await _rows(world)
    assert {(r.verdict, r.reason) for r in rows.values()} == {("skipped", "trigger deleted")}
    async with world.raw() as session:
        await session.execute(text("DELETE FROM triggers WHERE id = :t"), {"t": world.trigger_id})
        await session.commit()
    assert await _rows(world) == {}
    for event in (first, second):
        assert await _status(world, event) is ProcessingStatus.SKIPPED
    async with world.maker() as session:
        assert await close_open_batches(session, world.ctx, world.trigger_id, "again") == []


async def test_a_batch_of_a_deleted_trigger_settles_nothing(world):
    event = world.events[0]
    await _hold(world, event)
    async with world.maker() as session:
        await close_open_batches(session, world.ctx, world.trigger_id, "trigger deleted")
        await session.commit()
    async with world.raw() as session:
        await session.execute(text("DELETE FROM triggers WHERE id = :t"), {"t": world.trigger_id})
        await session.commit()
    service = _Service(None)
    firer = _firer(world, service)
    assert await firer.close(_batch(world, [event], reason="cancelled")) == 0
    assert await firer.fire(_batch(world, [event])) == 0
    service.fire.assert_not_awaited()
    assert await _rows(world) == {}
    assert await _status(world, event) is ProcessingStatus.SKIPPED
