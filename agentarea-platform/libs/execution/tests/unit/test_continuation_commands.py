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


@pytest.mark.asyncio
async def test_concurrent_continuation_grants_apply_only_the_first(monkeypatch):
    import asyncio

    from agentarea_execution.models import UpdateTaskGovernanceSnapshotResult
    from temporalio import workflow

    instance = _workflow()
    instance._waiting_for_continuation = True
    instance._continuation_failure_reason = "iteration_limit"
    persisted = asyncio.Event()
    calls: list[dict] = []

    async def execute_activity(_name, *, args, **_kwargs):
        calls.append(args[0].governance_snapshot)
        await persisted.wait()
        return UpdateTaskGovernanceSnapshotResult(success=True)

    monkeypatch.setattr(workflow, "patched", lambda _patch_id: True)
    monkeypatch.setattr(workflow, "execute_activity", execute_activity)

    def grant(extra: int) -> dict:
        policy = _policy(max_model_turns=3 + extra, run_budget_usd="1.00")
        return {
            "additional_iterations": extra,
            "effective_policy": policy,
            "governance_snapshot": {"effective_policy": policy, "revision": 2},
        }

    first = asyncio.ensure_future(instance.continue_execution(grant(3)))
    await asyncio.sleep(0)
    second = await instance.continue_execution(grant(1))
    third = await instance.continue_execution(grant(2))
    persisted.set()
    accepted = await first

    assert accepted["accepted"] is True
    assert second == {"accepted": False, "reason": "not_waiting_for_continuation"}
    assert third == {"accepted": False, "reason": "not_waiting_for_continuation"}
    assert len(calls) == 1
    assert instance.state.goal.max_iterations == 6
    assert instance._continuation_count == 1


@pytest.mark.parametrize(
    ("ceilings", "fixed"),
    [
        ({"iteration_limit": "3"}, True),
        ({"iteration_limit": "10"}, False),
        ({}, False),
    ],
)
def test_a_limit_a_policy_already_sets_at_its_ceiling_is_not_waited_on(ceilings, fixed):
    instance = _workflow()
    instance._workflow_metadata = {"governance_snapshot": {"limit_ceilings": ceilings}}

    assert instance._limit_at_policy_ceiling("iteration_limit") is fixed


def test_the_message_of_a_limit_fixed_by_policy_says_it_cannot_be_raised():
    instance = _workflow()
    instance._policy_fixed_limit = "iteration_limit"

    message = instance._termination_message("iteration_limit", "Maximum iterations reached (3)")

    assert message.startswith("Maximum iterations reached (3). A workspace")
    assert instance._termination_message("token_limit", "Token budget exhausted") == (
        "Token budget exhausted"
    )
