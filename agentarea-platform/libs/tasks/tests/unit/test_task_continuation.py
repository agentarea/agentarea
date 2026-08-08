from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_common.money import to_money
from agentarea_governance.domain.policies import (
    PolicyValidationError,
    effective_policy_from_json,
)
from agentarea_tasks.task_service import TaskService


def _policy(*, max_model_turns: int, run_budget_usd: str):
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
    )


def _waiting_task(task_id, policy):
    return SimpleNamespace(
        id=task_id,
        agent_id=uuid4(),
        workspace_id=str(uuid4()),
        status="waiting_for_continuation",
        execution_id=f"task-{task_id}",
        metadata={
            "governance_snapshot": {
                "requested_policy": {},
                "effective_policy": policy.to_json_dict(),
                "revision": 1,
            },
        },
    )


def _service(task, *, next_policy=None, result=None):
    service = object.__new__(TaskService)
    service.get_task = AsyncMock(return_value=task)
    service._resolve_effective_policy = AsyncMock(return_value=next_policy)
    service.workflow_service = SimpleNamespace(
        continue_execution=AsyncMock(
            return_value=result or {"accepted": True, "continuation_count": 1}
        )
    )
    return service


@pytest.mark.asyncio
async def test_continue_execution_forwards_money_as_string():
    task_id = uuid4()
    current_policy = _policy(max_model_turns=3, run_budget_usd="1.00")
    next_policy = _policy(max_model_turns=7, run_budget_usd="2.25")
    task = _waiting_task(task_id, current_policy)
    service = _service(task, next_policy=next_policy)

    result = await service.continue_execution(
        task_id,
        additional_iterations=4,
        additional_budget_usd=to_money("1.25"),
    )

    assert result["accepted"] is True
    service.workflow_service.continue_execution.assert_awaited_once()
    execution_id, payload = service.workflow_service.continue_execution.await_args.args
    assert execution_id == f"task-{task_id}"
    assert payload["additional_iterations"] == 4
    assert payload["additional_budget_usd"] == "1.25"
    assert payload["effective_policy"] == next_policy.to_json_dict()
    assert payload["governance_snapshot"]["effective_policy"] == next_policy.to_json_dict()
    assert payload["governance_snapshot"]["revision"] == 2
    assert payload["governance_snapshot"]["resolved_execution"] == next_policy.execution.model_dump(
        exclude_none=True
    )
    assert payload["governance_snapshot"]["requested_policy"] == {
        "budget": {"run_budget_usd": "2.25"},
        "execution": {"max_model_turns": 7},
    }


@pytest.mark.asyncio
async def test_continue_execution_rejects_non_waiting_task_without_signal():
    task_id = uuid4()
    service = _service(
        SimpleNamespace(id=task_id, status="running", execution_id=f"task-{task_id}")
    )

    result = await service.continue_execution(task_id, additional_iterations=2)

    assert result == {"accepted": False, "reason": "not_waiting_for_continuation"}
    service.workflow_service.continue_execution.assert_not_awaited()


@pytest.mark.asyncio
async def test_continue_execution_rejects_policy_ceiling_without_update():
    task_id = uuid4()
    current_policy = _policy(max_model_turns=3, run_budget_usd="1.00")
    task = _waiting_task(task_id, current_policy)
    service = _service(task)
    service._resolve_effective_policy.side_effect = PolicyValidationError(
        "task policy weakens workspace ceiling"
    )

    result = await service.continue_execution(task_id, additional_iterations=2)

    assert result == {"accepted": False, "reason": "policy_ceiling"}
    service.workflow_service.continue_execution.assert_not_awaited()
