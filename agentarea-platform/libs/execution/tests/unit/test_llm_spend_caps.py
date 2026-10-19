"""A cap on LLM spend stops a run on model spend alone; tool spend never counts to it."""

import logging
from decimal import Decimal
from unittest.mock import AsyncMock

from agentarea_execution.models import (
    AgentExecutionResume,
    ConversationResumeSnapshot,
    MonthlySpendCapResult,
)
from agentarea_execution.workflows.agent.budget import LLM_RUN_CAP_FAILURE_REASON
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_execution.workflows.helpers import BudgetTracker, EventManager
from agentarea_execution.workflows.models import AgentGoal
from temporalio import workflow as temporal_workflow
from temporalio.exceptions import ActivityError, ApplicationError, RetryState


def _workflow(monkeypatch, *spend_caps: dict) -> AgentExecutionWorkflow:
    monkeypatch.setattr(temporal_workflow, "logger", logging.getLogger("test-llm-cap"))
    monkeypatch.setattr(temporal_workflow, "patched", lambda _patch: True)
    workflow = AgentExecutionWorkflow()
    workflow.budget_tracker = BudgetTracker(Decimal("100"))
    workflow.state.agent_id = "agent-1"
    workflow.state.goal = AgentGoal(
        id="g",
        description="d",
        success_criteria=[],
        max_iterations=10,
        requires_human_approval=False,
        context={},
    )
    workflow.state.workspace_id = "ws-1"
    workflow.state.user_context_data = {"user_id": "alice", "workspace_id": "ws-1"}
    workflow.state.effective_policy = {
        "budget": {"run_budget_usd": "100", "spend_caps": list(spend_caps)},
        "tokens": {"max_tokens": 1_000_000},
    }
    return workflow


def _monthly_check(monkeypatch, llm_cap_message: str | None = None) -> list:
    requests: list = []

    async def execute_activity(_name, *, args, **_kwargs):
        requests.append(args[0])
        return MonthlySpendCapResult(
            exceeded=False,
            month_to_date_usd=Decimal("0"),
            currency="EUR",
            llm_cap_message=llm_cap_message,
        )

    monkeypatch.setattr(temporal_workflow, "execute_activity", execute_activity)
    return requests


async def test_a_monthly_llm_cap_reached_stops_the_run_before_its_first_turn(monkeypatch):
    llm_cap = {"amount_usd": "2", "category": "llm", "own_agent": True}
    workflow = _workflow(monkeypatch, llm_cap)
    requests = _monthly_check(monkeypatch, "Agent monthly LLM spend cap reached (2 EUR/2 EUR)")

    await workflow._check_monthly_spend_cap()

    [request] = requests
    assert (request.agent_id, request.llm_caps) == ("agent-1", [llm_cap])
    should_continue, reason, message = workflow._should_continue_execution()
    assert (should_continue, reason) == (False, "monthly_spend_cap_exceeded")
    assert message == "Agent monthly LLM spend cap reached (2 EUR/2 EUR)"


async def test_a_tools_or_run_cap_is_not_read_when_the_run_starts(monkeypatch):
    workflow = _workflow(
        monkeypatch,
        {"amount_usd": "2", "category": "tools", "own_agent": False},
        {"amount_usd": "2", "category": "llm", "own_agent": False, "period": "run"},
    )
    requests = _monthly_check(monkeypatch)

    await workflow._check_monthly_spend_cap()

    assert requests == []


def test_a_run_llm_cap_counts_model_spend_and_not_tool_spend(monkeypatch):
    workflow = _workflow(
        monkeypatch, {"amount_usd": "1", "category": "llm", "own_agent": False, "period": "run"}
    )

    workflow._account_inference_usage(cost=Decimal("0.6"), total_tokens=10, source="LLM call")
    # A paid tool call joins the run budget, not the LLM spend.
    workflow._budget.add_cost(Decimal("5"))
    assert workflow._should_continue_execution()[0] is True

    workflow._account_inference_usage(cost=Decimal("0.4"), total_tokens=10, source="LLM call")
    should_continue, reason, message = workflow._should_continue_execution()

    assert (should_continue, reason) == (False, LLM_RUN_CAP_FAILURE_REASON)
    assert message == "LLM spend cap of this run reached (1.0/1)"


async def test_a_run_stopped_at_its_llm_cap_does_not_wait_for_a_grant(monkeypatch):
    workflow = _workflow(monkeypatch)

    assert await workflow._await_continuation(LLM_RUN_CAP_FAILURE_REASON, "reached") is False


def test_a_resumed_run_carries_the_tasks_llm_spend_on(monkeypatch):
    workflow = _workflow(monkeypatch)
    snapshot = ConversationResumeSnapshot(head_seqs=[], tail_start=0, next_seq=4, current_iteration=2)

    workflow._adopt_resume(
        AgentExecutionResume(snapshot=snapshot, total_cost=Decimal("3"), llm_cost=Decimal("1.2"))
    )

    assert workflow.state.llm_cost_used == Decimal("1.2")


async def test_a_model_call_refused_at_a_monthly_cap_stops_the_run_as_the_start_check_does(
    monkeypatch,
):
    """The turn's or compaction's call refused mid-run ends the run without a grant."""
    workflow = _workflow(monkeypatch)
    workflow.state.current_iteration = 2
    workflow.event_manager = EventManager("task-1", "agent-1", "execution-1")
    monkeypatch.setattr(workflow, "_publish_events_immediately", AsyncMock())
    refusal = ApplicationError(
        "Workspace monthly LLM spend cap reached (2 EUR/2 EUR)",
        type="SpendCapReachedError",
        non_retryable=True,
    )

    async def refused_call():
        raise ActivityError(
            "activity failed",
            scheduled_event_id=1,
            started_event_id=2,
            identity="worker",
            activity_type="compact_messages_activity",
            activity_id="1",
            retry_state=RetryState.NON_RETRYABLE_FAILURE,
        ) from refusal

    monkeypatch.setattr(workflow, "_execute_traditional_iteration", refused_call)

    await workflow._execute_iteration()

    should_continue, reason, message = workflow._should_continue_execution()
    assert (should_continue, reason) == (False, "monthly_spend_cap_exceeded")
    assert message == "Workspace monthly LLM spend cap reached (2 EUR/2 EUR)"
    assert await workflow._await_continuation(reason, message) is False
