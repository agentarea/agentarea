from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_common.money import to_money
from agentarea_tasks.task_service import TaskService


def _service(task, result=None):
    service = object.__new__(TaskService)
    service.get_task = AsyncMock(return_value=task)
    service.workflow_service = SimpleNamespace(
        continue_execution=AsyncMock(
            return_value=result or {"accepted": True, "continuation_count": 1}
        )
    )
    return service


@pytest.mark.asyncio
async def test_continue_execution_forwards_money_as_string():
    task_id = uuid4()
    task = SimpleNamespace(
        id=task_id,
        status="waiting_for_continuation",
        execution_id=f"task-{task_id}",
    )
    service = _service(task)

    result = await service.continue_execution(
        task_id,
        additional_iterations=4,
        additional_budget_usd=to_money("1.25"),
    )

    assert result["accepted"] is True
    service.workflow_service.continue_execution.assert_awaited_once_with(
        f"task-{task_id}",
        {"additional_iterations": 4, "additional_budget_usd": "1.25"},
    )


@pytest.mark.asyncio
async def test_continue_execution_rejects_non_waiting_task_without_signal():
    task_id = uuid4()
    service = _service(
        SimpleNamespace(id=task_id, status="running", execution_id=f"task-{task_id}")
    )

    result = await service.continue_execution(task_id, additional_iterations=2)

    assert result == {"accepted": False, "reason": "not_waiting_for_continuation"}
    service.workflow_service.continue_execution.assert_not_awaited()
