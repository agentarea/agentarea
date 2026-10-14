"""A connector declares what its calls cost; one call is metered from that declaration."""

from decimal import Decimal

import pytest
from agentarea_common.tool_cost import (
    CostSourceKind,
    Payer,
    ToolCostError,
    connector_payers,
    meter,
    parse_cost_model,
    resolve_cost_model,
)


def test_no_declaration_is_an_unknown_cost():
    assert parse_cost_model(None).source is CostSourceKind.UNKNOWN


def test_a_rate_is_price_times_one_by_default():
    model = parse_cost_model({"source": "rate", "rate": {"amount": "0.488", "currency": "RUB"}})

    cost = meter(model, args={}, body=None)

    assert (cost.quantity, cost.unit, cost.vendor_cost, cost.currency) == (
        Decimal(1),
        "call",
        Decimal("0.488"),
        "RUB",
    )
    assert cost.source is CostSourceKind.RATE


def test_a_rate_quantity_can_come_from_an_argument_with_a_default():
    model = parse_cost_model(
        {
            "source": "rate",
            "unit": "phrase",
            "rate": {
                "amount": "0.01",
                "currency": "RUB",
                "quantity": {"arg": "num_phrases", "default": 50},
            },
        }
    )

    assert meter(model, args={"num_phrases": "200"}, body=None).vendor_cost == Decimal("2.00")
    assert meter(model, args={}, body=None).quantity == Decimal(50)


def test_a_rate_quantity_can_count_returned_items_or_read_a_number():
    counted = parse_cost_model(
        {
            "source": "rate",
            "rate": {"amount": "0.5", "currency": "USD", "quantity": {"count": "$.items"}},
        }
    )
    read = parse_cost_model(
        {
            "source": "rate",
            "rate": {"amount": "2", "currency": "USD", "quantity": {"path": "$.usage.pages"}},
        }
    )

    assert meter(counted, args={}, body={"items": [1, 2, 3]}).vendor_cost == Decimal("1.5")
    assert meter(read, args={}, body={"usage": {"pages": 4}}).vendor_cost == Decimal(8)


def test_a_reported_cost_is_read_from_the_response():
    model = parse_cost_model(
        {"source": "reported", "reported": {"path": "$.cost", "currency": "USD"}}
    )

    cost = meter(model, args={}, body={"cost": 0.0123, "tasks": []})

    assert (cost.vendor_cost, cost.currency, cost.source) == (
        Decimal("0.0123"),
        "USD",
        CostSourceKind.REPORTED,
    )


def test_a_reported_cost_can_come_from_mcp_meta():
    model = parse_cost_model(
        {"source": "reported", "reported": {"meta": "apify.com/cost_usd", "currency": "USD"}}
    )

    cost = meter(model, args={}, body=None, meta={"apify.com/cost_usd": "0.40"})

    assert cost.vendor_cost == Decimal("0.40")


def test_a_cost_the_response_does_not_carry_is_an_error_not_zero():
    model = parse_cost_model(
        {"source": "reported", "reported": {"path": "$.cost", "currency": "USD"}}
    )

    with pytest.raises(ToolCostError, match=r"\$\.cost"):
        meter(model, args={}, body={"tasks": []})


def test_free_unknown_and_settled_calls_have_no_line_at_call_time():
    for raw in ({"source": "free"}, None, {"source": "settled"}):
        assert meter(parse_cost_model(raw), args={}, body={}) is None


@pytest.mark.parametrize(
    "raw",
    [
        {"source": "bogus"},
        {"source": "rate"},
        {"source": "rate", "rate": {"amount": "-1", "currency": "RUB"}},
        {"source": "rate", "rate": {"amount": "1", "currency": "rub"}},
        {"source": "rate", "rate": {"amount": "1", "currency": "RUB", "quantity": {"from": "x"}}},
        {"source": "reported", "reported": {"currency": "USD"}},
        {"source": "reported", "reported": {"path": "cost", "currency": "USD"}},
    ],
)
def test_a_malformed_declaration_is_refused(raw):
    with pytest.raises(ToolCostError):
        parse_cost_model(raw)


def test_an_operation_declaration_overrides_the_connector_default():
    default = {"source": "rate", "rate": {"amount": "1", "currency": "RUB"}}
    own = {"source": "free"}

    assert resolve_cost_model(default, own).source is CostSourceKind.FREE
    assert resolve_cost_model(default, None).rate_amount == Decimal(1)
    assert resolve_cost_model(None, None).source is CostSourceKind.UNKNOWN


def test_payers_default_to_the_workspace_and_reject_unknown_values():
    assert connector_payers(None) == (Payer.WORKSPACE,)
    assert connector_payers(["workspace", "platform"]) == (Payer.WORKSPACE, Payer.PLATFORM)
    with pytest.raises(ToolCostError):
        connector_payers(["anyone"])
