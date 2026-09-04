import pytest
from agentarea_common.money import to_money
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_execution.workflows.helpers import BudgetTracker
from agentarea_execution.workflows.models import AgentGoal
from agentarea_governance.domain.policies import effective_policy_from_json


def _policy(*, max_model_turns: int, run_budget_usd: str) -> dict:
    return effective_policy_from_json(
        {
            "budget": {"run_budget_usd": run_budget_usd},
            "tokens": {
                "max_tokens": 20_000,
                "max_tokens_per_call": 2_000,
            },
            "execution": {
                "max_model_turns": max_model_turns,
                "max_tool_calls_per_turn": 10,
                "max_tool_calls_total": 100,
            },
        }
    ).to_json_dict()


def _workflow() -> AgentExecutionWorkflow:
    instance = AgentExecutionWorkflow()
    instance.budget_tracker = BudgetTracker(to_money("1.00"))
    instance.state.budget_usd = to_money("1.00")
    instance.state.effective_policy = _policy(
        max_model_turns=3,
        run_budget_usd="1.00",
    )
    instance.state.goal = AgentGoal(
        id="goal",
        description="finish",
        success_criteria=["done"],
        max_iterations=3,
        requires_human_approval=False,
        context={},
    )
    return instance


def test_update_budget_can_tighten_policy_and_keeps_accumulated_cost():
    instance = _workflow()
    instance.budget_tracker.cost = to_money("0.40")

    instance._handle_update_budget({"budget_usd": "0.75"})

    assert instance.budget_tracker.budget_limit == to_money("0.75")
    assert instance.budget_tracker.cost == to_money("0.40")
    assert instance.state.budget_usd == to_money("0.75")


def test_update_budget_cannot_bypass_governance_policy():
    instance = _workflow()

    with pytest.raises(
        ValueError,
        match="budget increases require a re-resolved governance snapshot",
    ):
        instance._handle_update_budget({"budget_usd": "2.50"})


def test_continuation_is_applied_once_and_duplicate_is_safe():
    instance = _workflow()
    instance._waiting_for_continuation = True
    instance._continuation_failure_reason = "iteration_limit"

    next_policy = _policy(max_model_turns=5, run_budget_usd="1.00")
    payload = {
        "additional_iterations": 2,
        "effective_policy": next_policy,
        "governance_snapshot": {
            "effective_policy": next_policy,
            "revision": 2,
        },
    }
    accepted = instance._apply_continuation(payload)
    duplicate = instance._apply_continuation(payload)

    assert accepted["accepted"] is True
    assert instance.state.goal.max_iterations == 5
    assert duplicate == {"accepted": False, "reason": "not_waiting_for_continuation"}


def test_budget_continuation_requires_budget_top_up():
    instance = _workflow()
    instance._waiting_for_continuation = True
    instance._continuation_failure_reason = "budget_exceeded"

    rejected = instance._apply_continuation({"additional_iterations": 2})

    assert rejected == {"accepted": False, "reason": "additional_budget_required"}
    assert instance._waiting_for_continuation is True


def test_continuation_requires_a_persistable_policy_revision():
    instance = _workflow()
    instance._waiting_for_continuation = True
    instance._continuation_failure_reason = "iteration_limit"

    rejected = instance._apply_continuation({"additional_iterations": 2})

    assert rejected == {
        "accepted": False,
        "reason": "governance_snapshot_required",
    }
    assert instance.state.goal.max_iterations == 3
    assert instance._waiting_for_continuation is True
