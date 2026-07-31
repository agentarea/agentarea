from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_common.money import to_money
from agentarea_governance.domain.policies import (
    BudgetPolicy,
    EffectivePolicy,
    ExecutionLimitsPolicy,
    TokenPolicy,
)
from agentarea_tasks.direct_task_manager import DirectTaskManager
from agentarea_tasks.domain.models import AgentTask


@pytest.mark.asyncio
async def test_iteration_limit_is_failed_in_direct_execution():
    repository = AsyncMock()
    manager = DirectTaskManager(repository)
    llm = SimpleNamespace(
        complete=AsyncMock(
            return_value=SimpleNamespace(
                content="",
                cost=0,
                usage=SimpleNamespace(
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_tokens=2,
                ),
                tool_calls=[
                    {
                        "id": "call-1",
                        "function": {"name": "unknown", "arguments": "{}"},
                    }
                ],
            )
        )
    )
    manager._resolve_agent = AsyncMock(return_value=(llm, "", []))
    task = AgentTask(
        title="Task",
        description="Task",
        query="Task",
        user_id=str(uuid4()),
        workspace_id=str(uuid4()),
        agent_id=uuid4(),
        status="running",
        created_at=datetime.now(UTC),
        effective_policy=EffectivePolicy(
            budget=BudgetPolicy(run_budget_usd=to_money("1.00")),
            tokens=TokenPolicy(max_tokens=1000, max_tokens_per_call=100),
            execution=ExecutionLimitsPolicy(
                max_model_turns=10,
                max_tool_calls_per_turn=10,
                max_tool_calls_total=100,
            ),
        ).to_json_dict(),
    )

    await manager._execute(task)

    assert task.status == "failed"
    assert task.error_message == "Maximum iterations reached (10)"
    assert task.result == {
        "success": False,
        "status": "failed",
        "failure_reason": "iteration_limit",
        "error": "Maximum iterations reached (10)",
        "total_cost": "0",
        "own_cost": "0",
        "total_tokens": 20,
        "total_tool_calls": 10,
    }
    assert llm.complete.await_count == 10
    repository.update_status.assert_awaited_once_with(
        task.id,
        "failed",
        result=task.result,
        error="Maximum iterations reached (10)",
    )


@pytest.mark.asyncio
async def test_completion_does_not_consume_direct_tool_call_quota():
    repository = AsyncMock()
    manager = DirectTaskManager(repository)
    usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)
    llm = SimpleNamespace(
        complete=AsyncMock(
            side_effect=[
                SimpleNamespace(
                    content="",
                    cost=0,
                    usage=usage,
                    tool_calls=[
                        {
                            "id": "call-tool",
                            "function": {"name": "unknown", "arguments": "{}"},
                        }
                    ],
                ),
                SimpleNamespace(
                    content="",
                    cost=0,
                    usage=usage,
                    tool_calls=[
                        {
                            "id": "call-completion",
                            "function": {
                                "name": "completion",
                                "arguments": '{"result":"done"}',
                            },
                        }
                    ],
                ),
            ]
        )
    )
    manager._resolve_agent = AsyncMock(return_value=(llm, "", []))
    task = AgentTask(
        title="Task",
        description="Task",
        query="Task",
        user_id=str(uuid4()),
        workspace_id=str(uuid4()),
        agent_id=uuid4(),
        status="running",
        created_at=datetime.now(UTC),
        effective_policy=EffectivePolicy(
            budget=BudgetPolicy(run_budget_usd=to_money("1.00")),
            tokens=TokenPolicy(max_tokens=1000, max_tokens_per_call=100),
            execution=ExecutionLimitsPolicy(
                max_model_turns=3,
                max_tool_calls_per_turn=1,
                max_tool_calls_total=1,
            ),
        ).to_json_dict(),
    )

    await manager._execute(task)

    assert task.status == "completed"
    assert task.result == {
        "response": "done",
        "total_cost": "0",
        "own_cost": "0",
        "total_tokens": 4,
        "total_tool_calls": 1,
    }
    assert llm.complete.await_count == 2
    repository.update_status.assert_awaited_once_with(
        task.id,
        "completed",
        result=task.result,
    )
