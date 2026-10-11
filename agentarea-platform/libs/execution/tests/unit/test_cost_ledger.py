"""Which ledger lines a stored workflow event stands for."""

from decimal import Decimal
from uuid import uuid4

from agentarea_execution.activities.agent.cost_ledger import cost_entries
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
    assert line.managed_by == "platform"
    assert str(line.agent_id) == AGENT_ID
    assert line.evidence == {"purpose": "compaction", "prompt_tokens": 900, "completion_tokens": 100}


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
