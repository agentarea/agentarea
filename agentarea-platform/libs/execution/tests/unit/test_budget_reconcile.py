"""Single-source-of-truth reconciliation between the per-request budget
and the governance policy run budget.

Both the loop-level PEP (BudgetTracker) and the call-level PEP (CostBudgetGuard)
must enforce the same ceiling. The tightest of the two wins (monotonic).
"""

from decimal import Decimal

from agentarea_execution.workflows.helpers import resolve_effective_budget


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


def test_neither_set_returns_none():
    assert resolve_effective_budget(None, None) is None
    assert resolve_effective_budget(None, {"budget": {}}) is None


def test_policy_without_budget_section_falls_back_to_request():
    assert resolve_effective_budget(Decimal("12"), {"tools": {"allowed": ["x"]}}) == Decimal("12")
