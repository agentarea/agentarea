from agentarea_common.money import to_money
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_execution.workflows.helpers import BudgetTracker
from agentarea_execution.workflows.models import AgentGoal


def _workflow() -> AgentExecutionWorkflow:
    instance = AgentExecutionWorkflow()
    instance.budget_tracker = BudgetTracker(to_money("1.00"))
    instance.state.budget_usd = to_money("1.00")
    instance.state.goal = AgentGoal(
        id="goal",
        description="finish",
        success_criteria=["done"],
        max_iterations=3,
        requires_human_approval=False,
        context={},
    )
    return instance


def test_update_budget_uses_money_and_keeps_accumulated_cost():
    instance = _workflow()
    instance.budget_tracker.cost = to_money("0.40")

    instance._handle_update_budget({"budget_usd": "2.50"})

    assert instance.budget_tracker.budget_limit == to_money("2.50")
    assert instance.budget_tracker.cost == to_money("0.40")
    assert instance.state.budget_usd == to_money("2.50")


def test_continuation_is_applied_once_and_duplicate_is_safe():
    instance = _workflow()
    instance._waiting_for_continuation = True
    instance._continuation_failure_reason = "iteration_limit"

    accepted = instance._apply_continuation({"additional_iterations": 2})
    duplicate = instance._apply_continuation({"additional_iterations": 2})

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
