"""A model call is refused at the workspace's, its agent's or an LLM monthly spend cap."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_governance.domain.policies import BudgetPolicy
from agentarea_tasks import model_spend_caps
from agentarea_tasks.domain.costs import CostCategory
from agentarea_tasks.infrastructure.cost_repository import SpendScope
from agentarea_tasks.model_spend_caps import SpendCapReachedError, refuse_model_call_at_spend_cap

NOW = datetime(2026, 10, 13, 12, tzinfo=UTC)
MONTH_START = datetime(2026, 10, 1, tzinfo=UTC)
AGENT = uuid4()
USER = UserContext(user_id="alice", workspace_id=str(uuid4()))


@pytest.fixture
def ledger(monkeypatch):
    """The month's spend per scope; every read is recorded."""
    spend: dict[SpendScope, Decimal] = {}
    reads: list[tuple[datetime, str, SpendScope]] = []

    class _Ledger:
        def __init__(self, session, user_context):
            assert user_context is USER

        async def sum_since(self, since, *, currency, agent_id=None, scope=None):
            scope = scope or SpendScope(agent_id=agent_id)
            reads.append((since, currency, scope))
            return spend.get(scope, Decimal("0"))

    monkeypatch.setattr(model_spend_caps, "CostEntryRepository", _Ledger)
    monkeypatch.setattr(
        model_spend_caps, "get_customer_pricing", lambda: SimpleNamespace(currency=lambda: "RUB")
    )
    return SimpleNamespace(spend=spend, reads=reads)


async def _refuse(budget: BudgetPolicy | None, agent_id: UUID | None = AGENT) -> None:
    await refuse_model_call_at_spend_cap(object(), USER, budget, agent_id, now=NOW)


async def test_a_call_once_the_workspace_monthly_cap_is_reached_is_refused(ledger):
    ledger.spend[SpendScope()] = Decimal("10.00")

    with pytest.raises(SpendCapReachedError) as raised:
        await _refuse(BudgetPolicy(monthly_spend_cap_usd=Decimal("10")))

    assert raised.value.reason == "Workspace monthly spend cap reached (10.00 RUB/10 RUB)"
    assert ledger.reads == [(MONTH_START, "RUB", SpendScope())]


async def test_a_call_once_the_agents_monthly_cap_is_reached_is_refused(ledger):
    ledger.spend[SpendScope()] = Decimal("4")
    ledger.spend[SpendScope(agent_id=AGENT)] = Decimal("3")

    with pytest.raises(SpendCapReachedError) as raised:
        await _refuse(
            BudgetPolicy(
                monthly_spend_cap_usd=Decimal("10"), agent_monthly_spend_cap_usd=Decimal("3")
            )
        )

    assert raised.value.reason == "Agent monthly spend cap reached (3 RUB/3 RUB)"


async def test_a_call_once_a_monthly_llm_cap_is_reached_is_refused(ledger):
    ledger.spend[SpendScope(category=CostCategory.MODEL)] = Decimal("2")

    with pytest.raises(SpendCapReachedError) as raised:
        await _refuse(
            BudgetPolicy.model_validate({"spend_caps": [{"amount_usd": "2", "category": "llm"}]})
        )

    assert raised.value.reason == "Workspace monthly LLM spend cap reached (2 RUB/2 RUB)"


async def test_a_call_below_every_cap_is_made(ledger):
    ledger.spend[SpendScope()] = Decimal("9.99")
    ledger.spend[SpendScope(agent_id=AGENT)] = Decimal("2.99")
    ledger.spend[SpendScope(category=CostCategory.MODEL)] = Decimal("1")

    await _refuse(
        BudgetPolicy.model_validate(
            {
                "monthly_spend_cap_usd": "10",
                "agent_monthly_spend_cap_usd": "3",
                "spend_caps": [{"amount_usd": "2", "category": "llm"}],
            }
        )
    )

    assert [scope for _, _, scope in ledger.reads] == [
        SpendScope(),
        SpendScope(agent_id=AGENT),
        SpendScope(category=CostCategory.MODEL),
    ]


async def test_an_agent_cap_is_not_read_for_a_call_of_no_agent(ledger):
    ledger.spend[SpendScope(agent_id=None)] = Decimal("99")

    await _refuse(BudgetPolicy(agent_monthly_spend_cap_usd=Decimal("3")), agent_id=None)

    assert ledger.reads == []


@pytest.mark.parametrize(
    "budget",
    [
        None,
        BudgetPolicy(),
        BudgetPolicy(run_budget_usd=Decimal("5")),
        BudgetPolicy.model_validate(
            {
                "spend_caps": [
                    {"amount_usd": "2", "category": "tools"},
                    {"amount_usd": "2", "category": "llm", "period": "run"},
                ]
            }
        ),
    ],
)
async def test_without_a_monthly_cap_the_ledger_is_not_read(ledger, budget):
    await _refuse(budget)

    assert ledger.reads == []
