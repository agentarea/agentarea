from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_streams.domain import (
    EventFilter,
    StreamEvent,
    SubscriptionKind,
    SubscriptionView,
    Verdict,
)
from agentarea_streams.domain.keys import task_id_for
from agentarea_triggers.batches import batch_workflow_id
from agentarea_triggers.channels.sender_admission import Admitted, Refused
from agentarea_triggers.domain.models import (
    ConditionVerdict,
    StreamTrigger,
    TriggerBatchWindow,
    TriggerFiring,
)
from agentarea_triggers.infrastructure.reactions import CausedExecutionRepository
from agentarea_triggers.stream_subscriber import (
    ConfigurerAuthority,
    SubscriptionFollowUpClaim,
    TriggerSubscriptionHandler,
)


def _sub(trigger_id):
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


def _event():
    return StreamEvent(
        type="push",
        source="webhook:github",
        data={"text": "go"},
        stream_id=uuid4(),
        workspace_id="w",
        created_by="u",
        event_key="k",
        received_at=datetime.now(UTC),
    )


def _trigger(**kw):
    return StreamTrigger(
        name="t",
        agent_id=uuid4(),
        created_by="owner",
        workspace_id="w",
        **kw,
    )


def _service():
    service = MagicMock()
    service.stream_service.get_stream = AsyncMock(return_value=SimpleNamespace(name="orders"))
    return service


class _Claim:
    def __init__(self, delivered_to=None):
        self._delivered_to = delivered_to

    async def delivered_to(self):
        return self._delivered_to


class _Batches:
    def __init__(self):
        self.added: list = []

    async def add(self, spec, event_id, *, workflow_id):
        self.added.append((spec, event_id, workflow_id))


def _handler(
    service, may_run=True, claim=None, sender_admission=None, contexts=None, batches=None
):
    authority = MagicMock()
    authority.may_run = AsyncMock(return_value=may_run)
    claim = claim or _Claim()

    def factory(_session, context):
        if contexts is not None:
            contexts.append(context)
        return service

    return TriggerSubscriptionHandler(
        event_broker=AsyncMock(),
        secret_manager_factory=MagicMock(),
        workflow_executor=MagicMock(),
        authority=authority,
        max_depth=8,
        trigger_service_factory=factory,
        follow_up_claim_factory=lambda _s, _sub, _e: cast(SubscriptionFollowUpClaim, claim),
        sender_admission=sender_admission,
        batches=batches or _Batches(),
        batch_cap=100,
    )


async def test_a_follow_up_already_routed_for_this_event_is_not_fired_again():
    trigger = _trigger()
    service = _service()
    service.get_trigger = AsyncMock(return_value=trigger)
    service.fire = AsyncMock()
    running = uuid4()
    result = await _handler(service, claim=_Claim(delivered_to=running)).handle(
        _sub(trigger.id), _event(), AsyncMock()
    )
    assert (result.verdict, result.task_id) == (Verdict.REACTED, running)
    service.fire.assert_not_awaited()


async def test_the_stream_path_fires_with_the_claim_and_retries_what_is_not_permanent():
    trigger = _trigger()
    service = _service()
    service.get_trigger = AsyncMock(return_value=trigger)
    service.fire = AsyncMock(return_value=TriggerFiring(outcome="reacted", task_id=uuid4()))
    claim = _Claim()
    await _handler(service, claim=claim).handle(_sub(trigger.id), _event(), AsyncMock())
    kwargs = service.fire.await_args.kwargs
    assert kwargs["follow_up_claim"] is claim
    assert kwargs["raise_retryable"] is True


async def test_a_firing_that_raises_leaves_no_outcome_for_the_dispatcher_to_record():
    trigger = _trigger()
    service = _service()
    service.get_trigger = AsyncMock(return_value=trigger)
    service.fire = AsyncMock(side_effect=ConnectionResetError("temporal went away"))
    with pytest.raises(ConnectionResetError):
        await _handler(service).handle(_sub(trigger.id), _event(), AsyncMock())


async def test_a_reaction_records_the_task_and_the_verdict_score():
    trigger = _trigger()
    service = _service()
    service.get_trigger = AsyncMock(return_value=trigger)
    task = uuid4()
    service.fire = AsyncMock(
        return_value=TriggerFiring(
            outcome="reacted",
            task_id=task,
            verdict=ConditionVerdict(verdict="met", score=0.7, reason="refund"),
            reason="refund",
        )
    )
    sub, event = _sub(trigger.id), _event()
    result = await _handler(service).handle(sub, event, AsyncMock())
    assert (result.verdict, result.task_id, result.score) == (Verdict.REACTED, task, 0.7)
    kwargs = service.fire.await_args.kwargs
    assert kwargs["task_id"] == task_id_for(sub.id, event.id)
    assert kwargs["provenance"].causation_id == str(event.id)
    assert kwargs["provenance"].origin_id == str(trigger.id)
    told = kwargs["event"]
    assert (told.stream_name, told.kind, told.key) == ("orders", "push", "k")
    recorder = service.trigger_execution_repository
    assert isinstance(recorder, CausedExecutionRepository)
    assert (recorder._cause.subscription_id, recorder._cause.event_id) == (sub.id, event.id)
    assert told.data == service.fire.await_args.args[1] == event.data


async def test_a_configurer_who_lost_access_stops_the_trigger():
    trigger = _trigger()
    service = _service()
    service.get_trigger = AsyncMock(return_value=trigger)
    service.fire = AsyncMock()
    service.trigger_repository.mark_needs_new_owner = AsyncMock(return_value=True)
    result = await _handler(service, may_run=False).handle(_sub(trigger.id), _event(), AsyncMock())
    assert result.verdict == Verdict.ERROR
    assert "configurer_lost_access" in (result.reason or "")
    service.trigger_repository.mark_needs_new_owner.assert_awaited_once_with(trigger.id)
    service.fire.assert_not_awaited()


async def test_a_stop_that_updated_no_row_is_not_reported_as_a_stop():
    trigger = _trigger()
    service = _service()
    service.get_trigger = AsyncMock(return_value=trigger)
    service.fire = AsyncMock()
    service.trigger_repository.mark_needs_new_owner = AsyncMock(return_value=False)
    with pytest.raises(RuntimeError, match="no row updated"):
        await _handler(service, may_run=False).handle(_sub(trigger.id), _event(), AsyncMock())
    service.fire.assert_not_awaited()


async def test_an_inactive_trigger_is_skipped_without_firing():
    trigger = _trigger(is_active=False)
    service = _service()
    service.get_trigger = AsyncMock(return_value=trigger)
    service.fire = AsyncMock()
    result = await _handler(service).handle(_sub(trigger.id), _event(), AsyncMock())
    assert result.verdict == Verdict.SKIPPED
    service.fire.assert_not_awaited()


async def test_membership_is_checked_before_the_agent_permission():
    permissions = AsyncMock()
    permissions.check.return_value = True
    with (
        patch(
            "agentarea_triggers.stream_subscriber.is_workspace_owner",
            AsyncMock(return_value=False),
        ),
        patch(
            "agentarea_triggers.stream_subscriber.check_workspace_membership",
            AsyncMock(return_value=False),
        ),
    ):
        allowed = await ConfigurerAuthority(graph=MagicMock(), permissions=permissions).may_run(
            AsyncMock(), user_id="gone", workspace_id="w", agent_id=uuid4()
        )
    assert allowed is False
    permissions.check.assert_not_awaited()


async def test_a_graph_outage_raises_instead_of_denying():
    with (
        patch(
            "agentarea_triggers.stream_subscriber.is_workspace_owner",
            AsyncMock(return_value=False),
        ),
        patch(
            "agentarea_triggers.stream_subscriber.check_workspace_membership",
            AsyncMock(side_effect=RuntimeError("openfga down")),
        ),
        pytest.raises(RuntimeError),
    ):
        await ConfigurerAuthority(graph=MagicMock(), permissions=AsyncMock()).may_run(
            AsyncMock(), user_id="u", workspace_id="w", agent_id=uuid4()
        )


class _Admission:
    def __init__(self, decision):
        self.decision = decision

    async def admit(self, _session, _trigger, _event, _door):
        return self.decision


def _telegram_door():
    return patch(
        "agentarea_triggers.stream_subscriber.event_admission",
        AsyncMock(return_value=MagicMock()),
    )


async def test_a_refused_telegram_sender_never_fires_the_agent():
    trigger = _trigger()
    service = _service()
    service.get_trigger = AsyncMock(return_value=trigger)
    service.fire = AsyncMock()
    handler = _handler(service, sender_admission=_Admission(Refused("not linked")))
    with _telegram_door():
        result = await handler.handle(_sub(trigger.id), _event(), AsyncMock())
    assert (result.verdict, result.reason) == (Verdict.SKIPPED, "not linked")
    service.fire.assert_not_awaited()


async def test_an_admitted_telegram_sender_runs_the_agent_as_themselves():
    trigger = _trigger()
    service = _service()
    service.get_trigger = AsyncMock(return_value=trigger)
    service.fire = AsyncMock(return_value=TriggerFiring(outcome="reacted", task_id=uuid4()))
    contexts: list = []
    handler = _handler(service, sender_admission=_Admission(Admitted("alice")), contexts=contexts)
    with _telegram_door():
        await handler.handle(_sub(trigger.id), _event(), AsyncMock())
    assert service.fire.await_args.kwargs["caller"] == "alice"
    # The service the task is created through acts for the sender, not the trigger owner.
    assert contexts[-1].user_id == "alice"


async def test_a_telegram_trigger_without_admission_lets_nobody_through():
    trigger = _trigger()
    service = _service()
    service.get_trigger = AsyncMock(return_value=trigger)
    service.fire = AsyncMock()
    with _telegram_door():
        result = await _handler(service).handle(_sub(trigger.id), _event(), AsyncMock())
    assert result.verdict == Verdict.ERROR
    service.fire.assert_not_awaited()


async def test_a_body_moved_to_files_is_fired_with_the_body_as_sent():
    trigger = _trigger()
    service = _service()
    service.get_trigger = AsyncMock(return_value=trigger)
    service.fire = AsyncMock(return_value=TriggerFiring(outcome="reacted", task_id=uuid4()))
    event = _event()
    event.data = {"headers": {}, "body": None, "body_ref": "events/s/e/body.json"}
    body = {"text": "a long mail"}
    with patch(
        "agentarea_triggers.stream_subscriber.event_body", AsyncMock(return_value=body)
    ) as read:
        await _handler(service).handle(_sub(trigger.id), event, AsyncMock())
    read.assert_awaited_once_with(event.data, "w")
    told = service.fire.await_args.kwargs["event"]
    assert told.data == service.fire.await_args.args[1]
    assert told.data["body"] == body


async def test_a_windowed_trigger_hands_the_event_to_its_open_batch_instead_of_firing():
    trigger = _trigger(batch=TriggerBatchWindow(window="60s", max_events=3))
    service = _service()
    service.get_trigger = AsyncMock(return_value=trigger)
    service.fire = AsyncMock()
    batches = _Batches()
    sub, event = _sub(trigger.id), _event()
    result = await _handler(service, batches=batches).handle(sub, event, AsyncMock())
    service.fire.assert_not_awaited()
    ((spec, event_id, workflow_id),) = batches.added
    assert workflow_id == batch_workflow_id(trigger.id, None)
    assert event_id == event.id
    assert (spec.trigger_id, spec.subscription_id) == (trigger.id, sub.id)
    assert (spec.window_seconds, spec.max_events, spec.caller) == (60.0, 3, None)
    assert (spec.workspace_id, spec.configured_by) == ("w", "u")
    assert result.verdict == Verdict.BATCHED
    assert result.workflow_id == workflow_id
    assert result.task_id is None


async def test_a_batch_without_a_count_fires_at_the_cap():
    trigger = _trigger(batch=TriggerBatchWindow(window="1h"))
    service = _service()
    service.get_trigger = AsyncMock(return_value=trigger)
    batches = _Batches()
    await _handler(service, batches=batches).handle(_sub(trigger.id), _event(), AsyncMock())
    assert batches.added[0][0].max_events == 100


async def test_each_event_meets_the_conditions_before_it_joins_a_batch():
    trigger = _trigger(batch=TriggerBatchWindow(max_events=3), conditions={"type": "rule"})
    service = _service()
    service.get_trigger = AsyncMock(return_value=trigger)
    service.evaluate_trigger_verdict = AsyncMock(
        return_value=ConditionVerdict(verdict="not_met", reason="a small order")
    )
    batches = _Batches()
    result = await _handler(service, batches=batches).handle(
        _sub(trigger.id), _event(), AsyncMock()
    )
    assert (result.verdict, result.reason) == (Verdict.SKIPPED, "a small order")
    assert batches.added == []


async def test_the_depth_limit_applies_to_each_event_before_its_batch():
    trigger = _trigger(batch=TriggerBatchWindow(max_events=3))
    service = _service()
    service.get_trigger = AsyncMock(return_value=trigger)
    batches = _Batches()
    event = _event()
    event.depth = 8
    result = await _handler(service, batches=batches).handle(_sub(trigger.id), event, AsyncMock())
    assert result.verdict == Verdict.SKIPPED
    assert batches.added == []


async def test_an_admitted_sender_gets_a_batch_of_their_own():
    trigger = _trigger(batch=TriggerBatchWindow(max_events=3))
    service = _service()
    service.get_trigger = AsyncMock(return_value=trigger)
    batches = _Batches()
    handler = _handler(
        service, sender_admission=_Admission(Admitted("alice")), batches=batches
    )
    with _telegram_door():
        result = await handler.handle(_sub(trigger.id), _event(), AsyncMock())
    ((spec, _, workflow_id),) = batches.added
    assert spec.caller == "alice"
    assert workflow_id == batch_workflow_id(trigger.id, "alice")
    assert result.workflow_id == workflow_id


async def test_a_refused_sender_never_joins_a_batch():
    trigger = _trigger(batch=TriggerBatchWindow(max_events=3))
    service = _service()
    service.get_trigger = AsyncMock(return_value=trigger)
    batches = _Batches()
    handler = _handler(
        service, sender_admission=_Admission(Refused("not linked")), batches=batches
    )
    with _telegram_door():
        result = await handler.handle(_sub(trigger.id), _event(), AsyncMock())
    assert result.verdict == Verdict.SKIPPED
    assert batches.added == []
