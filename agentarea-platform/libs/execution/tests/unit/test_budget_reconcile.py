"""Single-source-of-truth reconciliation between the per-request budget
and the governance policy run budget.

Both the loop-level PEP (BudgetTracker) and the call-level PEP (CostBudgetGuard)
must enforce the same ceiling. The tightest of the two wins (monotonic).
"""

import logging
from decimal import Decimal

import pytest
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_execution.workflows.helpers import BudgetTracker, resolve_effective_budget
from temporalio import workflow as temporal_workflow


def test_request_budget_only():
    assert resolve_effective_budget(Decimal("10"), None) == Decimal("10")


def test_policy_budget_only():
    policy = {"budget": {"run_budget_usd": "7.50"}}
    assert resolve_effective_budget(None, policy) == Decimal("7.50")


def test_policy_tighter_wins():
    policy = {"budget": {"run_budget_usd": "5.00"}}
    assert resolve_effective_budget(Decimal("10"), policy) == Decimal("5.00")


def test_request_tighter_wins():
    policy = {"budget": {"run_budget_usd": "20.00"}}
    assert resolve_effective_budget(Decimal("8"), policy) == Decimal("8")


def test_neither_set_is_rejected_instead_of_using_a_hidden_default():
    with pytest.raises(ValueError, match="run_budget_usd"):
        resolve_effective_budget(None, None)
    with pytest.raises(ValueError, match="run_budget_usd"):
        resolve_effective_budget(None, {"budget": {}})


def test_policy_without_budget_section_falls_back_to_request():
    assert resolve_effective_budget(Decimal("12"), {"tools": {"allowed": ["x"]}}) == Decimal("12")


def test_own_cost_excludes_delegated_child_spend():
    workflow = AgentExecutionWorkflow()
    workflow.budget_tracker = BudgetTracker(Decimal("10"))
    workflow.budget_tracker.cost = Decimal("3.25")
    workflow._delegated_cost = Decimal("1.50")

    assert workflow._own_cost == Decimal("1.75")


def test_every_inference_call_updates_shared_cost_and_token_counters(monkeypatch):
    monkeypatch.setattr(temporal_workflow, "logger", logging.getLogger("test-budget"))
    workflow = AgentExecutionWorkflow()
    workflow.budget_tracker = BudgetTracker(Decimal("10"))
    workflow.state.effective_policy = {"tokens": {"max_tokens": 1000}}

    workflow._record_inference_usage(
        cost=Decimal("0.25"),
        total_tokens=125,
        source="Context compaction",
    )

    assert workflow.budget_tracker.cost == Decimal("0.25")
    assert workflow.state.tokens_used == 125
