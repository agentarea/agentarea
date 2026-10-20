"""Loops through the platform stream are bounded (ADR-0040 §4).

A trigger on the platform stream sees its own tasks' outcomes there. Without a
guard, a trigger on ``task.completed`` would fire for the task it just started,
whose completion fires it again, forever.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from agentarea_streams.domain import (
    EventFilter,
    StreamEvent,
    SubscriptionKind,
    SubscriptionView,
    Verdict,
)
from agentarea_streams.domain.platform import PLATFORM_SOURCE_TYPE
from agentarea_triggers.domain.models import StreamTrigger, TriggerFiring
from agentarea_triggers.loop_guard import ChainEvent, ChainTask, own_task_in_chain
from agentarea_triggers.stream_subscriber import (
    SubscriptionFollowUpClaim,
    TriggerSubscriptionHandler,
)

MAX_DEPTH = 8


@pytest.fixture(autouse=True)
def _platform_entry_admits_anyone():
    with patch(
        "agentarea_triggers.stream_subscriber.event_admission", AsyncMock(return_value=None)
    ):
        yield


class _Chain:
    """Tasks and platform events in memory, keyed as the database keys them."""

    def __init__(self) -> None:
        self.tasks: dict[UUID, ChainTask] = {}
        self.events: dict[UUID, ChainEvent] = {}
        self.reads = 0

    def task_started(
        self, *, by_trigger: UUID | None = None, caused_by: UUID | None = None
    ) -> UUID:
        task_id = uuid4()
        self.tasks[task_id] = ChainTask(
            origin_type="trigger" if by_trigger else "user",
            origin_id=str(by_trigger) if by_trigger else "someone",
            causation_id=str(caused_by) if caused_by else None,
        )
        return task_id

    def outcome_of(self, task_id: UUID, depth: int) -> StreamEvent:
        event = _platform_event(task_id, depth)
        self.events[event.id] = ChainEvent(source_type=PLATFORM_SOURCE_TYPE, subject=str(task_id))
        return event

    async def task(self, task_id: UUID) -> ChainTask | None:
        self.reads += 1
        return self.tasks.get(task_id)

    async def event(self, event_id: UUID) -> ChainEvent | None:
        self.reads += 1
        return self.events.get(event_id)


def _platform_event(task_id: UUID, depth: int) -> StreamEvent:
    return StreamEvent(
        type="task.completed",
        source="platform",
        subject=str(task_id),
        data={"task_id": str(task_id), "status": "completed"},
        stream_id=uuid4(),
        workspace_id="w",
        created_by="u",
        event_key=str(uuid4()),
        received_at=datetime.now(UTC),
        depth=depth,
        source_type=PLATFORM_SOURCE_TYPE,
    )


async def test_an_outcome_of_a_task_the_trigger_started_is_its_own():
    chain = _Chain()
    trigger = uuid4()
    first = chain.task_started()
    first_outcome = chain.outcome_of(first, depth=1)
    second = chain.task_started(by_trigger=trigger, caused_by=first_outcome.id)
    assert (
        await own_task_in_chain(
            chain, trigger_id=trigger, event=chain.outcome_of(second, 2), max_hops=MAX_DEPTH
        )
        == second
    )


async def test_an_outcome_further_down_the_chain_is_still_its_own():
    """X starts a task, its outcome fires Y, Y's outcome reaches X: X does not react."""
    chain = _Chain()
    x, y = uuid4(), uuid4()
    by_x = chain.task_started(by_trigger=x)
    by_y = chain.task_started(by_trigger=y, caused_by=chain.outcome_of(by_x, 1).id)
    assert (
        await own_task_in_chain(
            chain, trigger_id=x, event=chain.outcome_of(by_y, 2), max_hops=MAX_DEPTH
        )
        == by_x
    )


async def test_another_triggers_task_outcome_is_not_its_own():
    chain = _Chain()
    task = chain.task_started(by_trigger=uuid4())
    assert (
        await own_task_in_chain(
            chain, trigger_id=uuid4(), event=chain.outcome_of(task, 1), max_hops=MAX_DEPTH
        )
        is None
    )


async def test_an_event_from_outside_the_platform_reads_nothing():
    chain = _Chain()
    event = _platform_event(uuid4(), 0).model_copy(update={"source_type": "github"})
    assert await own_task_in_chain(chain, trigger_id=uuid4(), event=event, max_hops=8) is None
    assert chain.reads == 0


def _sub(trigger_id: UUID) -> SubscriptionView:
    return SubscriptionView(
        id=uuid4(),
        workspace_id="w",
        created_by="u",
        stream_id=uuid4(),
        kind=SubscriptionKind.TRIGGER,
        trigger_id=trigger_id,
        filter=EventFilter(),
        output_stream_ids=[],
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


class _Claim:
    async def delivered_to(self):
        return None


def _handler(service, chain: _Chain) -> TriggerSubscriptionHandler:
    authority = MagicMock()
    authority.may_run = AsyncMock(return_value=True)
    return TriggerSubscriptionHandler(
        event_broker=AsyncMock(),
        secret_manager_factory=MagicMock(),
        workflow_executor=MagicMock(),
        authority=authority,
        max_depth=MAX_DEPTH,
        trigger_service_factory=lambda _s, _c: service,
        follow_up_claim_factory=lambda _s, _sub, _e: cast(SubscriptionFollowUpClaim, _Claim()),
        causation_chain=lambda _session, _workspace: chain,
        batches=AsyncMock(),
        batch_cap=100,
    )


def _service(trigger: StreamTrigger) -> MagicMock:
    service = MagicMock()
    service.get_trigger = AsyncMock(return_value=trigger)
    service.stream_service.get_stream = AsyncMock(return_value=SimpleNamespace(name="platform"))
    service.fire = AsyncMock(return_value=TriggerFiring(outcome="reacted", task_id=uuid4()))
    return service


def _trigger() -> StreamTrigger:
    return StreamTrigger(name="on-call", agent_id=uuid4(), created_by="owner", workspace_id="w")


async def test_a_trigger_on_the_platform_stream_does_not_refire_itself_forever():
    """A user's task fails, the trigger fires once; its own task's outcome does not fire it."""
    chain = _Chain()
    trigger = _trigger()
    service = _service(trigger)
    handler = _handler(service, chain)
    failed = chain.task_started()
    first = chain.outcome_of(failed, depth=1)

    reacted = await handler.handle(_sub(trigger.id), first, AsyncMock())
    assert reacted.verdict is Verdict.REACTED
    provenance = service.fire.await_args.kwargs["provenance"]
    assert provenance.depth == 1
    assert provenance.causation_id == str(first.id)

    on_call = chain.task_started(by_trigger=trigger.id, caused_by=first.id)
    again = await handler.handle(_sub(trigger.id), chain.outcome_of(on_call, 2), AsyncMock())
    assert again.verdict is Verdict.SKIPPED
    assert str(on_call) in (again.reason or "")
    assert service.fire.await_count == 1


async def test_an_event_past_the_causation_depth_is_skipped_with_a_reason():
    chain = _Chain()
    trigger = _trigger()
    service = _service(trigger)
    event = chain.outcome_of(chain.task_started(), depth=MAX_DEPTH)
    result = await _handler(service, chain).handle(_sub(trigger.id), event, AsyncMock())
    assert result.verdict is Verdict.SKIPPED
    assert "causation depth" in (result.reason or "")
    service.fire.assert_not_awaited()


async def test_two_triggers_feeding_each_other_each_fire_once_per_chain():
    """X fires on Y's outcomes and Y on X's: the chain ends where it comes back to X."""
    chain = _Chain()
    x, y = _trigger(), _trigger()
    handlers = {x.id: _handler(_service(x), chain), y.id: _handler(_service(y), chain)}
    event = chain.outcome_of(chain.task_started(), depth=1)
    fired = 0
    turn = x
    while True:
        result = await handlers[turn.id].handle(_sub(turn.id), event, AsyncMock())
        if result.verdict is not Verdict.REACTED:
            break
        fired += 1
        task = chain.task_started(by_trigger=turn.id, caused_by=event.id)
        event = chain.outcome_of(task, event.depth + 1)
        turn = y if turn is x else x
    assert result.verdict is Verdict.SKIPPED
    assert fired == 2
