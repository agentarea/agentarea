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
    pre_call_cost,
    resolve_cost_model,
    settle_url,
    settled_cost,
    tool_connection,
)


def test_no_declaration_is_an_unknown_cost():
    assert parse_cost_model(None).source is CostSourceKind.UNKNOWN


def test_a_rate_is_price_times_one_by_default():
    model = parse_cost_model({"source": "rate", "rate": {"amount": "0.488", "currency": "EUR"}})

    cost = meter(model, args={}, body=None)

    assert (cost.quantity, cost.unit, cost.vendor_cost, cost.currency) == (
        Decimal(1),
        "call",
        Decimal("0.488"),
        "EUR",
    )
    assert cost.source is CostSourceKind.RATE


def test_a_rate_quantity_can_come_from_an_argument_with_a_default():
    model = parse_cost_model(
        {
            "source": "rate",
            "unit": "phrase",
            "rate": {
                "amount": "0.01",
                "currency": "EUR",
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


def test_free_and_unknown_calls_have_no_line_at_call_time():
    for raw in ({"source": "free"}, None):
        assert meter(parse_cost_model(raw), args={}, body={}) is None


@pytest.mark.parametrize(
    "raw",
    [
        {"source": "bogus"},
        {"source": "rate"},
        {"source": "rate", "rate": {"amount": "-1", "currency": "EUR"}},
        {"source": "rate", "rate": {"amount": "1", "currency": "rub"}},
        {"source": "rate", "rate": {"amount": "1", "currency": "EUR", "quantity": {"from": "x"}}},
        {"source": "reported", "reported": {"currency": "USD"}},
        {"source": "reported", "reported": {"path": "cost", "currency": "USD"}},
    ],
)
def test_a_malformed_declaration_is_refused(raw):
    with pytest.raises(ToolCostError):
        parse_cost_model(raw)


def test_an_operation_declaration_overrides_the_connector_default():
    default = {"source": "rate", "rate": {"amount": "1", "currency": "EUR"}}
    own = {"source": "free"}

    assert resolve_cost_model(default, own).source is CostSourceKind.FREE
    assert resolve_cost_model(default, None).rate_amount == Decimal(1)
    assert resolve_cost_model(None, None).source is CostSourceKind.UNKNOWN


def test_payers_default_to_the_workspace_and_reject_unknown_values():
    assert connector_payers(None) == (Payer.WORKSPACE,)
    assert connector_payers(["workspace", "platform"]) == (Payer.WORKSPACE, Payer.PLATFORM)
    with pytest.raises(ToolCostError):
        connector_payers(["anyone"])


def test_a_rate_is_an_estimate_unless_declared_exact_and_a_reported_cost_is_exact():
    rate = {"source": "rate", "rate": {"amount": "0.488", "currency": "EUR"}}
    reported = {"source": "reported", "reported": {"path": "$.cost", "currency": "USD"}}

    assert meter(parse_cost_model(rate), args={}, body=None).exact is False
    assert meter(parse_cost_model({**rate, "exact": True}), args={}, body=None).exact is True
    assert meter(parse_cost_model(reported), args={}, body={"cost": 1}).exact is True
    with pytest.raises(ToolCostError, match="exact"):
        parse_cost_model({**rate, "exact": "yes"})


def test_usdc_is_usd():
    model = parse_cost_model({"source": "rate", "rate": {"amount": "0.01", "currency": "USDC"}})

    assert meter(model, args={}, body=None).currency == "USD"


def test_the_cost_before_a_call_is_known_from_a_rate_on_a_constant_or_an_argument():
    per_phrase = parse_cost_model(
        {
            "source": "rate",
            "rate": {"amount": "0.01", "currency": "EUR", "quantity": {"arg": "n", "default": 5}},
        }
    )
    per_item = parse_cost_model(
        {"source": "rate", "rate": {"amount": "1", "currency": "USD", "quantity": {"count": "$.x"}}}
    )

    assert pre_call_cost(per_phrase, args={"n": 3}).vendor_cost == Decimal("0.03")
    assert pre_call_cost(per_item, args={}) is None
    assert pre_call_cost(parse_cost_model(None), args={}) is None
    assert pre_call_cost(parse_cost_model({"source": "free"}), args={}) is None


def test_a_declared_estimate_sizes_a_call_whose_cost_is_known_only_afterwards():
    model = parse_cost_model(
        {
            "source": "reported",
            "reported": {"path": "$.cost", "currency": "USD"},
            "estimate": {"amount": "0.05", "currency": "USD"},
        }
    )

    before = pre_call_cost(model, args={})

    assert (before.vendor_cost, before.currency, before.exact) == (Decimal("0.05"), "USD", False)
    assert meter(model, args={}, body={"cost": "0.02"}).vendor_cost == Decimal("0.02")


APIFY = {
    "source": "settled",
    "estimate": {"amount": "0.10", "currency": "USD"},
    "settled": {
        "fetch": {
            "url": "https://api.apify.com/v2/actor-runs/{run_id}",
            "params": {"run_id": "$.data.id"},
            "cost": "$.data.usageTotalUsd",
            "currency": "USD",
            "done": {"path": "$.data.status", "in": ["SUCCEEDED", "FAILED"]},
        }
    },
}


def test_a_settled_cost_is_the_estimate_now_with_the_parameters_to_fetch_it_later():
    model = parse_cost_model(APIFY)

    cost = meter(model, args={}, body={"data": {"id": "run-1"}})

    assert (cost.vendor_cost, cost.currency, cost.source, cost.exact) == (
        Decimal("0.10"),
        "USD",
        CostSourceKind.SETTLED,
        False,
    )
    assert cost.settle_params == {"run_id": "run-1"}
    assert model.settle.url == "https://api.apify.com/v2/actor-runs/{run_id}"
    assert model.settle.done_in == ("SUCCEEDED", "FAILED")


def test_a_settled_cost_reads_its_parameters_from_the_results_meta():
    raw = {
        **APIFY,
        "settled": {
            "fetch": {**APIFY["settled"]["fetch"], "params": {"run_id": {"meta": "runId"}}}
        },
    }

    cost = meter(parse_cost_model(raw), args={}, body=None, meta={"runId": "run-2"})

    assert cost.settle_params == {"run_id": "run-2"}


def test_a_settled_declaration_without_its_fetch_or_with_a_foreign_url_parameter_is_malformed():
    with pytest.raises(ToolCostError, match="settled"):
        parse_cost_model({"source": "settled"})
    fetch = {**APIFY["settled"]["fetch"], "url": "https://api.apify.com/v2/actor-runs/{other}"}
    with pytest.raises(ToolCostError, match="other"):
        parse_cost_model({**APIFY, "settled": {"fetch": fetch}})
    with pytest.raises(ToolCostError, match="estimate"):
        parse_cost_model({**APIFY, "estimate": {"amount": "1", "currency": "EUR"}})


def test_settlement_reads_the_cost_once_the_run_is_done():
    model = parse_cost_model(APIFY)

    running = settled_cost(model, {"data": {"status": "RUNNING"}})
    done = settled_cost(model, {"data": {"status": "SUCCEEDED", "usageTotalUsd": 0.0123}})

    assert running is None
    assert (done.vendor_cost, done.currency, done.exact) == (Decimal("0.0123"), "USD", True)
    assert settle_url(model, {"run_id": "run 1/x"}) == (
        "https://api.apify.com/v2/actor-runs/run%201%2Fx"
    )


def test_a_connection_can_set_its_own_cost_unless_the_platform_pays():
    default = {"source": "rate", "rate": {"amount": "1", "currency": "USD"}}
    own = {"source": "rate", "rate": {"amount": "0.2", "currency": "USD"}}

    connection = tool_connection(
        connection_id="c",
        connector="x",
        tool="t",
        platform_managed=False,
        payers=None,
        cost=default,
        override=own,
    )

    assert connection.cost_model.rate_amount == Decimal("0.2")
    with pytest.raises(ToolCostError, match="platform"):
        tool_connection(
            connection_id="c",
            connector="x",
            tool="t",
            platform_managed=True,
            payers=["platform"],
            cost=default,
            override=own,
        )


def test_a_connection_cannot_set_a_settled_cost_that_would_send_its_credential_elsewhere():
    with pytest.raises(ToolCostError, match="settled"):
        tool_connection(
            connection_id="c",
            connector="x",
            tool="t",
            platform_managed=False,
            payers=None,
            cost=None,
            override=APIFY,
        )


def test_a_reported_cost_can_sit_inside_a_meta_value():
    model = parse_cost_model(
        {
            "source": "reported",
            "reported": {
                "meta": "com.apify/ActorRun",
                "path": "$.usageTotalUsd",
                "currency": "USD",
            },
        }
    )

    cost = meter(model, args={}, body=None, meta={"com.apify/ActorRun": {"usageTotalUsd": 0.42}})

    assert cost.vendor_cost == Decimal("0.42")
    with pytest.raises(ToolCostError, match="usageTotalUsd"):
        meter(model, args={}, body=None, meta={"com.apify/ActorRun": {}})
