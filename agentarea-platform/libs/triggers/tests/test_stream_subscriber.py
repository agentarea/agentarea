from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_streams.domain import (
    EventFilter,
    JournaledEvent,
    SubscriptionKind,
    SubscriptionView,
    Verdict,
)
from agentarea_streams.domain.keys import task_id_for
from agentarea_triggers.channels.sender_admission import Admitted, Refused
from agentarea_triggers.domain.models import ConditionVerdict, TriggerFiring, WebhookTrigger
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
    )


def _event():
    return JournaledEvent(
        type="push",
        source="webhook:github",
        data={"text": "go"},
        stream_id=uuid4(),
        sequence=12,
        event_key="k",
        received_at=datetime.now(UTC),
    )


def _trigger(**kw):
    return WebhookTrigger(
        name="t",
        agent_id=uuid4(),
        created_by="owner",
        workspace_id="w",
        webhook_id="wh-1234567890abcd",
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


def _handler(service, may_run=True, claim=None, sender_admission=None, contexts=None):
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
        trigger_service_factory=factory,
        follow_up_claim_factory=lambda _s, _sub, _e: cast(SubscriptionFollowUpClaim, claim),
        sender_admission=sender_admission,
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
    assert kwargs["task_id"] == task_id_for(sub.id, event.sequence)
    assert kwargs["provenance"].causation_id == str(event.id)
    assert kwargs["provenance"].origin_id == str(trigger.id)
    told = kwargs["event"]
    assert (told.stream_name, told.kind, told.key, told.sequence) == (
        "orders",
        "push",
        "k",
        event.sequence,
    )
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

    async def admit(self, _session, _trigger, _data):
        return self.decision


async def test_a_refused_telegram_sender_never_fires_the_agent():
    trigger = _trigger(webhook_type="telegram")
    service = _service()
    service.get_trigger = AsyncMock(return_value=trigger)
    service.fire = AsyncMock()
    handler = _handler(service, sender_admission=_Admission(Refused("not linked")))
    result = await handler.handle(_sub(trigger.id), _event(), AsyncMock())
    assert (result.verdict, result.reason) == (Verdict.SKIPPED, "not linked")
    service.fire.assert_not_awaited()


async def test_an_admitted_telegram_sender_runs_the_agent_as_themselves():
    trigger = _trigger(webhook_type="telegram")
    service = _service()
    service.get_trigger = AsyncMock(return_value=trigger)
    service.fire = AsyncMock(return_value=TriggerFiring(outcome="reacted", task_id=uuid4()))
    contexts: list = []
    handler = _handler(service, sender_admission=_Admission(Admitted("alice")), contexts=contexts)
    await handler.handle(_sub(trigger.id), _event(), AsyncMock())
    assert service.fire.await_args.kwargs["caller"] == "alice"
    # The service the task is created through acts for the sender, not the trigger owner.
    assert contexts[-1].user_id == "alice"


async def test_a_telegram_trigger_without_admission_lets_nobody_through():
    trigger = _trigger(webhook_type="telegram")
    service = _service()
    service.get_trigger = AsyncMock(return_value=trigger)
    service.fire = AsyncMock()
    result = await _handler(service).handle(_sub(trigger.id), _event(), AsyncMock())
    assert result.verdict == Verdict.ERROR
    service.fire.assert_not_awaited()
