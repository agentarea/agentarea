"""Processors against the migrated schema: created by an agent, run by the router.

The runner here runs the harness with the local bash and python3 the way the
sandbox does; ``down`` makes it the sandbox being unreachable. Set
STREAMS_TEST_DATABASE_URL.
"""

import os
import subprocess
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
from agentarea_streams.application.forward import ForwardHandler
from agentarea_streams.application.processor import ProcessorHandler
from agentarea_streams.application.router import EventRouter, ReactionsFailedError
from agentarea_streams.application.stream_service import StreamService
from agentarea_streams.domain import (
    EventFilter,
    HandlerResult,
    ReactionTally,
    StreamEvent,
    StreamInUseError,
    StreamManagedByPlatformError,
    SubscriptionKind,
    Verdict,
)
from agentarea_streams.domain.enums import GAVE_UP_REASON
from agentarea_streams.domain.errors import (
    NotAProcessorError,
    ProcessorCodeError,
    ProcessorLoopError,
    ProcessorRuntimeUnavailableError,
)
from agentarea_streams.domain.keys import event_id_for, processor_output_id
from agentarea_streams.domain.processor import (
    MAX_RESULT_BYTES,
    TIMEOUT_SECONDS,
    CodeRun,
    sandbox_session,
)
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

BIG_ORDERS = """
def process(event):
    if event["kind"].startswith("order.") and event["data"].get("amount", 0) > 100:
        return [{"stream": "big-orders", "kind": event["kind"], "data": event["data"]}]
    return None
"""
FAILING = "def process(event):\n    raise RuntimeError('no amount on ' + event['kind'])\n"


class _Runner:
    def __init__(self):
        self.down = False
        self.calls: list[dict] = []

    async def run(self, *, workspace_id, session, command, timeout_seconds, max_output_bytes):
        self.calls.append(
            {
                "workspace_id": workspace_id,
                "session": session,
                "timeout_seconds": timeout_seconds,
                "max_output_bytes": max_output_bytes,
            }
        )
        if self.down:
            raise ProcessorRuntimeUnavailableError("sandbox returned HTTP 503")
        done = subprocess.run(["bash", "-c", command], capture_output=True, timeout=30, check=False)
        return CodeRun(
            exit_code=done.returncode,
            stdout=done.stdout[:max_output_bytes].decode(),
            stdout_truncated=len(done.stdout) > max_output_bytes,
            stderr=done.stderr.decode() if done.returncode else "",
        )


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

    def scoped():
        return workspace_scope(ctx.workspace_id)

    async def service_call(fn):
        with scoped(), patch(GRANT, new=AsyncMock()):
            async with maker() as session:
                result = await fn(
                    StreamService(RepositoryFactory(session, ctx), EventStreamSettings())
                )
                await session.commit()
                return result

    source = await service_call(lambda s: s.create_stream(name="orders", description=""))
    big = await service_call(lambda s: s.create_stream(name="big-orders", description=""))
    processor = await service_call(
        lambda s: s.create_processor(
            stream_id=source.id,
            output_stream_ids=[big.id],
            code=BIG_ORDERS,
            event_filter=EventFilter(),
        )
    )
    yield SimpleNamespace(
        engine=engine,
        maker=maker,
        raw=raw,
        ctx=ctx,
        call=service_call,
        source=source,
        big=big,
        processor=processor,
    )
    async with raw() as session:
        for table in ("streams", "event_outbox"):
            await session.execute(
                text(f"DELETE FROM {table} WHERE workspace_id = :ws"),  # noqa: S608
                {"ws": ctx.workspace_id},
            )
        await session.commit()
    await engine.dispose()


def _event(world, *, kind="order.paid", amount=250, key="o1", depth=0) -> StreamEvent:
    return StreamEvent(
        id=event_id_for(world.source.id, key),
        type=kind,
        source="webhook",
        data={"amount": amount},
        stream_id=world.source.id,
        workspace_id=world.ctx.workspace_id,
        created_by="u",
        event_key=key,
        received_at=datetime.now(UTC),
        correlation_id="chain-1",
        depth=depth,
        source_type="generic",
    )


def _router(world, runner, reactions, bus):
    return EventRouter(
        session_factory=world.maker,
        handlers={
            SubscriptionKind.TRIGGER: _Triggers(),
            SubscriptionKind.FORWARD: ForwardHandler(EventStreamSettings(), bus),
            SubscriptionKind.EXTERNAL: _Triggers(),
            SubscriptionKind.PROCESSOR: ProcessorHandler(EventStreamSettings(), bus, runner),
        },
        reactions=reactions,
        notices=_Notices(),
    )


async def test_a_processor_writes_what_its_code_returns_linked_to_the_event(world):
    runner, reactions, bus = _Runner(), _Reactions(), _Bus()
    event = _event(world)
    await _router(world, runner, reactions, bus).handle(event.to_bus())

    result = reactions.rows[(world.processor.id, event.id)]
    assert result.verdict is Verdict.REACTED
    (written,) = bus.published
    assert written.id == processor_output_id(world.processor.id, event.id, 0)
    assert result.derived_event_ids == [written.id]
    assert written.stream_id == world.big.id
    assert (written.type, written.data) == ("order.paid", {"amount": 250})
    assert written.causation_id == str(event.id)
    assert written.correlation_id == "chain-1"
    assert written.depth == 1
    assert written.source_type == "generic"
    assert runner.calls == [
        {
            "workspace_id": world.ctx.workspace_id,
            "session": sandbox_session(world.processor.id),
            "timeout_seconds": TIMEOUT_SECONDS,
            "max_output_bytes": MAX_RESULT_BYTES,
        }
    ]


async def test_a_redelivered_event_writes_the_same_events(world):
    runner, bus = _Runner(), _Bus()
    event = _event(world)
    await _router(world, runner, _Reactions(), bus).handle(event.to_bus())
    await _router(world, runner, _Reactions(), bus).handle(event.to_bus())
    assert len(bus.published) == 1


async def test_an_event_the_code_drops_is_skipped(world):
    runner, reactions, bus = _Runner(), _Reactions(), _Bus()
    event = _event(world, amount=5)
    await _router(world, runner, reactions, bus).handle(event.to_bus())
    result = reactions.rows[(world.processor.id, event.id)]
    assert result.verdict is Verdict.SKIPPED
    assert result.reason == "process() wrote no events"
    assert bus.published == []


async def test_code_that_raises_is_an_error_reaction_and_not_retried(world):
    await world.call(
        lambda s: s.update_processor(world.source.id, world.processor.id, code=FAILING)
    )
    runner, reactions, bus = _Runner(), _Reactions(), _Bus()
    event = _event(world)
    await _router(world, runner, reactions, bus).handle(event.to_bus())
    result = reactions.rows[(world.processor.id, event.id)]
    assert result.verdict is Verdict.ERROR
    assert result.reason == "RuntimeError: no amount on order.paid (processor.py line 2)"
    assert bus.published == []


async def test_an_output_to_a_stream_not_declared_is_an_error_reaction(world):
    code = 'def process(event):\n    return [{"stream": "orders", "kind": "x", "data": {}}]\n'
    await world.call(lambda s: s.update_processor(world.source.id, world.processor.id, code=code))
    reactions, bus = _Reactions(), _Bus()
    event = _event(world)
    await _router(world, _Runner(), reactions, bus).handle(event.to_bus())
    result = reactions.rows[(world.processor.id, event.id)]
    assert result.verdict is Verdict.ERROR
    assert "not one of this processor's outputs (big-orders)" in (result.reason or "")
    assert bus.published == []


async def test_a_sandbox_outage_is_redelivered_then_dead_lettered_as_an_error(world):
    runner, reactions, bus = _Runner(), _Reactions(), _Bus()
    runner.down = True
    router = _router(world, runner, reactions, bus)
    event = _event(world)
    with pytest.raises(ReactionsFailedError):
        await router.handle(event.to_bus())
    assert (world.processor.id, event.id) not in reactions.rows

    await router.give_up(event.to_bus())
    assert reactions.rows[(world.processor.id, event.id)].reason == GAVE_UP_REASON

    runner.down = False
    await router.handle(event.to_bus())
    assert reactions.rows[(world.processor.id, event.id)].verdict is Verdict.REACTED
    assert len(bus.published) == 1


async def test_past_the_causation_depth_the_code_never_runs(world):
    runner, reactions, bus = _Runner(), _Reactions(), _Bus()
    event = _event(world, depth=EventStreamSettings().FORWARD_DEPTH)
    await _router(world, runner, reactions, bus).handle(event.to_bus())
    result = reactions.rows[(world.processor.id, event.id)]
    assert result.verdict is Verdict.ERROR
    assert "causation depth" in (result.reason or "")
    assert runner.calls == []


async def test_a_processor_that_names_its_own_input_never_runs(world):
    async with world.raw() as session:
        await session.execute(
            text("UPDATE stream_subscriptions SET output_stream_ids = :o WHERE id = :s"),
            {"o": f'["{world.source.id}"]', "s": world.processor.id},
        )
        await session.commit()
    runner, reactions = _Runner(), _Reactions()
    event = _event(world)
    await _router(world, runner, reactions, _Bus()).handle(event.to_bus())
    result = reactions.rows[(world.processor.id, event.id)]
    assert result.verdict is Verdict.ERROR
    assert "own input" in (result.reason or "")
    assert runner.calls == []


async def test_a_processor_is_refused_its_own_input_and_the_platform_stream(world):
    with pytest.raises(ProcessorLoopError, match="own input"):
        await world.call(
            lambda s: s.create_processor(
                stream_id=world.source.id,
                output_stream_ids=[world.big.id, world.source.id],
                code=BIG_ORDERS,
                event_filter=EventFilter(),
            )
        )
    with pytest.raises(ProcessorLoopError, match="own input"):
        await world.call(
            lambda s: s.update_processor(
                world.source.id, world.processor.id, output_stream_ids=[world.source.id]
            )
        )
    platform, _ = await world.call(lambda s: s.ensure_platform_stream())
    with pytest.raises(StreamManagedByPlatformError):
        await world.call(
            lambda s: s.create_processor(
                stream_id=world.source.id,
                output_stream_ids=[platform.id],
                code=BIG_ORDERS,
                event_filter=EventFilter(),
            )
        )


async def test_code_that_cannot_run_is_refused_at_create_and_update(world):
    with pytest.raises(ProcessorCodeError, match="does not parse"):
        await world.call(
            lambda s: s.create_processor(
                stream_id=world.source.id,
                output_stream_ids=[world.big.id],
                code="def process(event:\n",
                event_filter=EventFilter(),
            )
        )
    with pytest.raises(ProcessorCodeError, match="secret"):
        await world.call(
            lambda s: s.update_processor(
                world.source.id,
                world.processor.id,
                code=f'API_KEY = "sk-abcdefghijklmnop0123"\n{BIG_ORDERS}',  # pragma: allowlist secret
            )
        )
    stored = await world.call(lambda s: s.get_processor(world.source.id, world.processor.id))
    assert stored.code == BIG_ORDERS


async def test_a_forward_is_not_a_processor_and_a_stream_written_to_cannot_go(world):
    forward = await world.call(
        lambda s: s.create_forward(
            stream_id=world.source.id, output_stream_ids=[world.big.id], event_filter=EventFilter()
        )
    )
    with pytest.raises(NotAProcessorError):
        await world.call(lambda s: s.get_processor(world.source.id, forward.id))
    await world.call(lambda s: s.delete_forward(world.source.id, forward.id))
    with pytest.raises(StreamInUseError) as refused:
        await world.call(lambda s: s.delete_stream(world.big.id))
    assert refused.value.processors == [(world.processor.id, world.source.id)]
    assert refused.value.forwards == []
    assert f"processor {world.processor.id} on stream {world.source.id} writes into it" in str(
        refused.value
    )
    assert "streams_delete_processor" in str(refused.value)

    await world.call(lambda s: s.delete_processor(world.source.id, world.processor.id))
    await world.call(lambda s: s.delete_stream(world.big.id))


class _PoolWatchingRunner(_Runner):
    """Records how many pooled connections are checked out while the code runs."""

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.checked_out: list[int] = []

    async def run(self, **kwargs):
        self.checked_out.append(self.engine.sync_engine.pool.checkedout())
        return await super().run(**kwargs)


async def test_the_code_runs_with_no_database_connection_held(world):
    runner, reactions, bus = _PoolWatchingRunner(world.engine), _Reactions(), _Bus()
    event = _event(world)
    await _router(world, runner, reactions, bus).handle(event.to_bus())
    assert runner.checked_out == [0]
    assert reactions.rows[(world.processor.id, event.id)].verdict is Verdict.REACTED
    assert len(bus.published) == 1


async def test_a_processor_deleted_while_its_code_ran_writes_nothing(world):
    class _DeletingRunner(_Runner):
        async def run(self, **kwargs):
            async with world.raw() as session:
                await session.execute(
                    text("DELETE FROM stream_subscriptions WHERE id = :s"),
                    {"s": world.processor.id},
                )
                await session.commit()
            return await super().run(**kwargs)

    reactions, bus = _Reactions(), _Bus()
    event = _event(world)
    await _router(world, _DeletingRunner(), reactions, bus).handle(event.to_bus())
    assert (world.processor.id, event.id) not in reactions.rows
    assert bus.published == []
