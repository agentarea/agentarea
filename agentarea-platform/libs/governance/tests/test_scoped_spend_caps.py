"""A monthly spend cap can be narrowed to a client, a connection or one of its tools."""

from decimal import Decimal

import pytest
from agentarea_governance.domain.policies import BudgetPolicy, PolicyResolver
from agentarea_governance.domain.rules import (
    PolicyEffect,
    PolicyRule,
    PolicySubjectType,
    assert_enforceable,
    is_scoped_spend_cap,
    rules_to_document,
)


def _cap(subject=PolicySubjectType.WORKSPACE, subject_id="ws-1", **params):
    return PolicyRule(
        subject_type=subject,
        subject_id=subject_id,
        target="spend",
        effect=PolicyEffect.CAP,
        params={"period": "month", **params},
    )


def test_a_connection_cap_compiles_to_a_scoped_cap_not_the_workspace_cap():
    document = rules_to_document([_cap(amount_usd="5", connection_id="conn-1", tool="web_search")])

    assert document.budget.monthly_spend_cap_usd is None
    [cap] = document.budget.spend_caps
    assert (cap.amount_usd, cap.connection_id, cap.tool, cap.own_agent, cap.client_id) == (
        Decimal(5),
        "conn-1",
        "web_search",
        False,
        None,
    )


def test_a_cap_bound_to_an_agent_is_scoped_to_that_agent():
    document = rules_to_document(
        [_cap(PolicySubjectType.AGENT, "agent-1", amount_usd="1", connection_id="conn-1")]
    )

    [cap] = document.budget.spend_caps
    assert cap.own_agent is True


def test_a_client_cap_names_the_client():
    [cap] = rules_to_document([_cap(amount_usd="2", client_id="client-1")]).budget.spend_caps

    assert cap.client_id == "client-1"


def test_scoped_caps_from_every_layer_all_apply():
    higher = BudgetPolicy(spend_caps=[{"amount_usd": "5", "connection_id": "a"}])
    lower = BudgetPolicy(spend_caps=[{"amount_usd": "1", "tool": "t", "connection_id": "a"}])

    merged = PolicyResolver()._merge_budget(higher, lower)

    assert [c.amount_usd for c in merged.spend_caps] == [Decimal(5), Decimal(1)]


def test_a_client_or_currency_cap_is_monthly():
    with pytest.raises(ValueError, match="month"):
        assert_enforceable(_cap(amount_usd="1", period="run", client_id="client-1"))
    with pytest.raises(ValueError, match="month"):
        assert_enforceable(_cap(amount_usd="1", period="run", currency="RUB"))


def test_a_connection_or_tool_cap_can_be_per_run():
    rule = _cap(amount_usd="1", period="run", connection_id="conn-1", tool="web_search")
    assert_enforceable(rule)

    document = rules_to_document([rule])

    assert document.budget.run_budget_usd is None
    [cap] = document.budget.spend_caps
    assert (cap.period, cap.connection_id, cap.tool, cap.category) == (
        "run",
        "conn-1",
        "web_search",
        None,
    )


@pytest.mark.parametrize("period", ["month", "run"])
@pytest.mark.parametrize("category", ["llm", "tools"])
def test_a_category_cap_compiles_to_a_scoped_cap_of_that_category(category, period):
    rule = _cap(PolicySubjectType.AGENT, "agent-1", amount_usd="2", period=period, category=category)
    assert_enforceable(rule)

    budget = rules_to_document([rule]).budget

    assert (budget.monthly_spend_cap_usd, budget.agent_monthly_spend_cap_usd) == (None, None)
    assert budget.run_budget_usd is None
    [cap] = budget.spend_caps
    assert (cap.amount_usd, cap.category, cap.own_agent) == (Decimal(2), category, True)
    assert cap.period == ("run" if period == "run" else None)


def test_an_llm_cap_cannot_name_a_client_connection_or_tool():
    for scope in ({"client_id": "c"}, {"connection_id": "conn-1"}):
        with pytest.raises(ValueError, match="tool spend"):
            assert_enforceable(_cap(amount_usd="1", category="llm", **scope))


def test_an_unknown_category_is_refused():
    with pytest.raises(ValueError, match="category"):
        assert_enforceable(_cap(amount_usd="1", category="wallet"))


def test_a_monthly_scoped_cap_serializes_without_period_or_category():
    """Snapshots stored before category caps existed must round-trip byte for byte."""
    from agentarea_governance.domain.policies import effective_policy_from_json

    old_snapshot = {
        "budget": {
            "run_budget_usd": "2.25",
            "spend_caps": [{"amount_usd": "5", "own_agent": False, "connection_id": "c"}],
        },
        "source_policy_ids": [],
        "resolver_version": "policy-resolver-v1",
    }
    budget = rules_to_document([_cap(amount_usd="5", connection_id="c")]).budget

    assert effective_policy_from_json(old_snapshot).to_json_dict() == old_snapshot
    assert budget.model_dump(mode="json", exclude_none=True)["spend_caps"] == [
        {"amount_usd": "5", "own_agent": False, "connection_id": "c"}
    ]


def test_a_rule_is_scoped_when_it_names_a_client_connection_or_tool():
    assert is_scoped_spend_cap({"amount_usd": "1", "tool": "t"})
    assert not is_scoped_spend_cap({"amount_usd": "1", "period": "month"})


def test_a_policy_without_scoped_caps_serializes_as_it_did_before_they_existed():
    """A run's continuation compares its stored snapshot to the policy's JSON.

    Snapshots stored before spend_caps existed have no such key; a policy with none
    must serialize without it, or every in-flight continuation is refused.
    """
    from agentarea_governance.domain.policies import effective_policy_from_json

    old_snapshot = {
        "budget": {"run_budget_usd": "2.25"},
        "execution": {"max_model_turns": 7},
        "source_policy_ids": [],
        "resolver_version": "policy-resolver-v1",
    }

    assert effective_policy_from_json(old_snapshot).to_json_dict() == old_snapshot
