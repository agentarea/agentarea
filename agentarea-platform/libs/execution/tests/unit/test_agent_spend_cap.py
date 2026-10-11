"""A run stops once its agent's month-to-date spend reaches the agent's cap."""

import logging
from decimal import Decimal

from agentarea_execution.models import MonthlySpendCapResult
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_execution.workflows.helpers import BudgetTracker
from temporalio import workflow as temporal_workflow


def _workflow(monkeypatch, *, agent_cap: str) -> AgentExecutionWorkflow:
    monkeypatch.setattr(temporal_workflow, "logger", logging.getLogger("test-agent-cap"))
    monkeypatch.setattr(temporal_workflow, "patched", lambda _patch: True)
    workflow = AgentExecutionWorkflow()
    workflow.budget_tracker = BudgetTracker(Decimal("100"))
    workflow.state.agent_id = "agent-1"
    workflow.state.workspace_id = "ws-1"
    workflow.state.user_context_data = {"user_id": "alice", "workspace_id": "ws-1"}
    workflow.state.effective_policy = {
        "budget": {"agent_monthly_spend_cap_usd": agent_cap},
        "tokens": {"max_tokens": 1_000_000},
    }
    return workflow


def _read_spend(monkeypatch, agent_mtd: str, currency: str = "USD") -> list:
    requests: list = []

    async def execute_activity(_name, *, args, **_kwargs):
        requests.append(args[0])
        return MonthlySpendCapResult(
            exceeded=False,
            month_to_date_usd=Decimal("0"),
            currency=currency,
            agent_exceeded=Decimal(agent_mtd) >= args[0].agent_cap_usd,
            agent_month_to_date_usd=Decimal(agent_mtd),
            agent_cap_usd=args[0].agent_cap_usd,
        )

    monkeypatch.setattr(temporal_workflow, "execute_activity", execute_activity)
    return requests


async def test_the_cap_check_reads_the_agents_own_spend(monkeypatch):
    workflow = _workflow(monkeypatch, agent_cap="5")
    requests = _read_spend(monkeypatch, "1")

    await workflow._check_monthly_spend_cap()

    [request] = requests
    assert (request.agent_id, request.agent_cap_usd, request.cap_usd) == (
        "agent-1",
        Decimal("5"),
        None,
    )
    assert workflow._monthly_cap_message is None


async def test_an_agent_already_at_its_cap_does_not_start(monkeypatch):
    workflow = _workflow(monkeypatch, agent_cap="5")
    _read_spend(monkeypatch, "5")

    await workflow._check_monthly_spend_cap()

    assert workflow._monthly_cap_message == "Agent monthly spend cap reached (5 USD/5 USD)"
    should_continue, reason, _message = workflow._should_continue_execution()
    assert (should_continue, reason) == (False, "monthly_spend_cap_exceeded")


async def test_model_calls_that_cross_the_cap_stop_the_run(monkeypatch):
    workflow = _workflow(monkeypatch, agent_cap="5")
    _read_spend(monkeypatch, "4")
    await workflow._check_monthly_spend_cap()

    workflow._account_inference_usage(cost=Decimal("0.6"), total_tokens=10, source="LLM call")
    assert workflow._monthly_cap_message is None

    workflow._account_inference_usage(cost=Decimal("0.4"), total_tokens=10, source="LLM call")
    assert workflow._monthly_cap_message == "Agent monthly spend cap reached (5.0 USD/5 USD)"


async def test_wallet_payments_count_where_usd_is_the_billing_currency(monkeypatch):
    workflow = _workflow(monkeypatch, agent_cap="5")
    _read_spend(monkeypatch, "4")
    await workflow._check_monthly_spend_cap()

    workflow.state.service_cost_used += Decimal("1")
    workflow._enforce_agent_spend_cap()

    assert workflow._monthly_cap_message is not None


async def test_wallet_payments_in_usd_do_not_count_against_a_rub_cap(monkeypatch):
    workflow = _workflow(monkeypatch, agent_cap="500")
    _read_spend(monkeypatch, "499", currency="RUB")
    await workflow._check_monthly_spend_cap()

    workflow.state.service_cost_used += Decimal("3")
    workflow._enforce_agent_spend_cap()

    assert workflow._monthly_cap_message is None


async def test_a_run_without_an_agent_cap_never_reads_agent_spend(monkeypatch):
    workflow = _workflow(monkeypatch, agent_cap="5")
    workflow.state.effective_policy = {"tokens": {"max_tokens": 1_000_000}}
    requests = _read_spend(monkeypatch, "100")

    await workflow._check_monthly_spend_cap()
    workflow._account_inference_usage(cost=Decimal("50"), total_tokens=10, source="LLM call")

    assert requests == []
    assert workflow._monthly_cap_message is None
