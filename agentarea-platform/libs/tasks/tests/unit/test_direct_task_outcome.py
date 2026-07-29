from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
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
    )

    await manager._execute(task)

    assert task.status == "failed"
    assert task.error_message == "Maximum iterations reached (10)"
    assert task.result == {
        "success": False,
        "status": "failed",
        "failure_reason": "iteration_limit",
        "error": "Maximum iterations reached (10)",
    }
    assert llm.complete.await_count == 10
    repository.update_status.assert_awaited_once_with(
        task.id,
        "failed",
        result=task.result,
        error="Maximum iterations reached (10)",
    )
