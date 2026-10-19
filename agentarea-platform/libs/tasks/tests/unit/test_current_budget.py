"""A run's monthly caps are read as the workspace and agent set them now, not as frozen."""

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_governance.domain.policies import BudgetPolicy, ScopedSpendCap
from agentarea_tasks import model_spend_caps
from agentarea_tasks.model_spend_caps import current_budget

AGENT = uuid4()
USER = UserContext(user_id="alice", workspace_id=str(uuid4()))


def _resolving(monkeypatch, live: BudgetPolicy | None) -> list[dict]:
    calls: list[dict] = []

    class _Resolver:
        def __init__(self, factory):
            pass

        async def resolve(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(budget=live)

    monkeypatch.setattr(model_spend_caps, "GovernancePolicyResolver", _Resolver)
    monkeypatch.setattr(model_spend_caps, "RepositoryFactory", lambda session, ctx: None)
    return calls


@pytest.mark.asyncio
async def test_a_cap_lowered_after_the_run_started_is_the_one_checked(monkeypatch):
    calls = _resolving(
        monkeypatch,
        BudgetPolicy(
            monthly_spend_cap_usd=Decimal("0.01"),
            spend_caps=[ScopedSpendCap(amount_usd=Decimal("2"), category="llm")],
        ),
    )
    frozen = BudgetPolicy(
        monthly_spend_cap_usd=Decimal("500"),
        agent_monthly_spend_cap_usd=Decimal("100"),
        run_budget_usd=Decimal("1"),
        spend_caps=[
            ScopedSpendCap(amount_usd=Decimal("0.5"), category="tools", period="run"),
            ScopedSpendCap(amount_usd=Decimal("50"), category="llm"),
        ],
    )

    budget = await current_budget(object(), USER, AGENT, frozen)

    assert budget is not None
    assert budget.monthly_spend_cap_usd == Decimal("0.01")
    assert budget.agent_monthly_spend_cap_usd is None
    assert budget.run_budget_usd == Decimal("1")
    assert budget.spend_caps == [
        ScopedSpendCap(amount_usd=Decimal("0.5"), category="tools", period="run"),
        ScopedSpendCap(amount_usd=Decimal("2"), category="llm"),
    ]
    assert calls == [
        {"workspace_id": USER.workspace_id, "agent_id": AGENT, "user_id": USER.user_id}
    ]


@pytest.mark.asyncio
async def test_a_cap_added_while_the_run_goes_applies_to_a_run_that_froze_none(monkeypatch):
    _resolving(monkeypatch, BudgetPolicy(agent_monthly_spend_cap_usd=Decimal("3")))

    budget = await current_budget(object(), USER, AGENT, None)

    assert budget == BudgetPolicy(agent_monthly_spend_cap_usd=Decimal("3"))


@pytest.mark.asyncio
async def test_no_budget_anywhere_is_none(monkeypatch):
    _resolving(monkeypatch, None)

    assert await current_budget(object(), USER, AGENT, None) is None
