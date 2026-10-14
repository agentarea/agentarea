"""Which ledger lines a stored workflow event stands for."""

from decimal import Decimal
from uuid import uuid4

from agentarea_execution.activities.agent.cost_ledger import cost_entries
from agentarea_common.tool_cost import CostSourceKind, Payer
from agentarea_tasks.domain.costs import CostCategory, CostSource, CostSubjectType

TASK_ID, AGENT_ID = str(uuid4()), str(uuid4())


def _event(event_type: str, **data) -> dict:
    return {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "timestamp": "2026-10-08T12:00:00+00:00",
        "data": {"task_id": TASK_ID, "agent_id": AGENT_ID, **data},
    }


def _lines(event: dict, currency: str = "RUB"):
    return cost_entries(event, workspace_id="ws-1", created_by="alice", billing_currency=currency)


def test_a_priced_model_call_is_one_model_line_with_its_token_evidence():
    event = _event(
        "llm.call.completed",
        model_id="model-1",
        model_name="kimi-k3",
        managed_by="platform",
        cost="1.5",
        provider_cost_usd="0.018",
        purpose="compaction",
        usage={"cost": "1.5", "usage": {"prompt_tokens": 900, "completion_tokens": 100}},
    )

    [line] = _lines(event)

    assert line.category == CostCategory.MODEL
    assert line.source == CostSource.TOKEN_PRICING
    assert line.subject_type == CostSubjectType.MODEL_INSTANCE
    assert (line.subject_id, line.subject_name) == ("model-1", "kimi-k3")
    assert (line.amount, line.currency) == (Decimal("1.5"), "RUB")
    assert line.provider_cost_usd == Decimal("0.018")
    assert line.payer == Payer.PLATFORM
    assert str(line.agent_id) == AGENT_ID
    assert line.evidence == {
        "purpose": "compaction",
        "prompt_tokens": 900,
        "completion_tokens": 100,
    }


def test_a_model_line_keeps_how_much_of_the_prompt_came_from_the_cache():
    event = _event(
        "llm.call.completed",
        cost="0.48",
        usage={
            "cost": "0.48",
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 100,
                "total_tokens": 1100,
                "cached_prompt_tokens": 800,
                "cache_creation_tokens": 0,
            },
        },
    )

    [line] = _lines(event)

    assert line.evidence["cached_prompt_tokens"] == 800
    assert line.evidence["cache_creation_tokens"] == 0


def test_a_free_call_and_an_unpaid_event_have_no_lines():
    assert _lines(_event("llm.call.completed", cost="0")) == []
    assert _lines(_event("tool.result", tool_name="read_file", service_cost="0")) == []
    assert _lines(_event("llm.call.started")) == []


def test_a_tool_that_paid_a_service_and_ran_a_model_is_two_lines():
    event = _event(
        "tool.result",
        tool_name="generate_video",
        tool_call_id="call-7",
        server_instance_id="srv-1",
        server_name="Studio",
        model_cost="40",
        service_cost="0.25",
        payment={
            "protocol": "x402",
            "amount_usd": "0.25",
            "tx_hash": "0xabc",
            "recipient": "0xdef",
            "response_body": "large vendor body",
        },
    )

    model, service = _lines(event)

    assert (model.category, model.source) == (CostCategory.MODEL, CostSource.TOOL_REPORTED)
    assert (model.amount, model.currency) == (Decimal("40"), "RUB")
    assert (service.category, service.source) == (CostCategory.SERVICE, CostSource.X402)
    assert (model.payer, service.payer) == (Payer.WORKSPACE, Payer.PER_CALL)
    assert (service.amount, service.currency, service.provider_cost_usd) == (
        Decimal("0.25"),
        "USD",
        Decimal("0.25"),
    )
    for line in (model, service):
        assert line.subject_type == CostSubjectType.TOOL
        assert (line.subject_id, line.subject_name, line.call_ref) == (
            "srv-1",
            "generate_video",
            "call-7",
        )
    assert service.evidence["payment"] == {
        "protocol": "x402",
        "amount_usd": "0.25",
        "tx_hash": "0xabc",
        "recipient": "0xdef",
    }


def test_an_event_without_a_task_is_not_attributed():
    event = _event("llm.call.completed", cost="1")
    event["data"].pop("task_id")

    assert _lines(event) == []


def test_a_metered_call_is_not_a_line_of_its_event():
    """The tool-call layer wrote its lines when it ran; the event only reports them."""
    event = _event(
        "tool.result",
        tool_name="yandex__web_search",
        tool_call_id="call-9",
        source="openapi",
        cost="0.74",
        payer="platform",
        cost_metered=True,
        service_cost="0.25",
        payment={"protocol": "x402", "amount_usd": "0.25", "idempotency_key": "pay-1"},
    )

    assert _lines(event) == []


def test_a_payment_is_one_line_whichever_build_recorded_it():
    """An in-flight run replays events the old build persisted, then events the new one did.

    An old event (no ``cost_metered``) is the payment's only record and is still a
    line, keyed by the event. A new event's payment was written by the layer, keyed by
    the call, and is not a line of the event. Replaying both twice stores one line each.
    """
    from agentarea_governance.tool_calls import ToolUsage
    from agentarea_tasks.domain.costs import tool_call_entry
    from datetime import UTC, datetime

    payment = {"protocol": "x402", "amount_usd": "0.25", "idempotency_key": "pay-1"}
    old = _event("tool.result", tool_call_id="call-1", service_cost="0.25", payment=payment)
    new = _event(
        "tool.result",
        tool_call_id="call-2",
        service_cost="0.25",
        payment=payment,
        cost_metered=True,
    )
    layer_line = tool_call_entry(
        ToolUsage(
            line_key=f"{TASK_ID}:call-2:payment:pay-1",
            call_id=f"{TASK_ID}:call-2",
            workspace_id="ws-1",
            user_id="alice",
            agent_id=None,
            task_id=TASK_ID,
            client_id=None,
            tool_name="fetch",
            connection_id=None,
            connector=None,
            tool=None,
            payer=Payer.PER_CALL,
            source=CostSourceKind.REPORTED,
            quantity=Decimal(1),
            unit="payment",
            vendor_cost=Decimal("0.25"),
            vendor_currency="USD",
            amount=Decimal("0.25"),
            currency="USD",
            occurred_at=datetime.now(UTC),
        )
    )

    stored: dict = {}
    for _ in range(2):
        for line in [*_lines(old), *_lines(new), layer_line]:
            stored.setdefault((line.event_id, line.category), line)

    service = [line for line in stored.values() if line.category == CostCategory.SERVICE]
    assert sorted(line.call_ref for line in service) == sorted(["call-1", f"{TASK_ID}:call-2"])
    assert {line.payer for line in service} == {Payer.PER_CALL}


def test_a_held_model_call_is_a_line_billing_priced_with_its_hold_to_capture():
    billing = {
        "amount": "2.85",
        "currency": "RUB",
        "vendor_cost": "0.02",
        "vendor_currency": "USD",
        "estimate": True,
        "settle": "capture",
        "hold_id": "hold-1",
    }
    event = _event(
        "llm.call.completed",
        model_id="model-1",
        managed_by="platform",
        cost="2.85",
        provider_cost_usd="0.02",
        usage={"cost": "2.85", "usage": {"prompt_tokens": 10, "billing": billing}},
    )

    [line] = _lines(event, currency="EUR")

    assert (line.amount, line.currency, line.estimate) == (Decimal("2.85"), "RUB", True)
    assert (line.vendor_cost, line.vendor_currency) == (Decimal("0.02"), "USD")
    assert (line.evidence["hold_id"], line.evidence["settle"]) == ("hold-1", "capture")


def test_a_model_call_from_before_holds_keeps_its_cost_in_the_billing_currency():
    event = _event(
        "llm.call.completed",
        model_id="model-1",
        managed_by="platform",
        cost="1.5",
        usage={"cost": "1.5", "usage": {"prompt_tokens": 10}},
    )

    [line] = _lines(event)

    assert (line.amount, line.currency, line.estimate) == (Decimal("1.5"), "RUB", False)
    assert "hold_id" not in line.evidence
