from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_tasks.domain.models import AgentTask
from agentarea_tasks.task_service import TaskService


def _task(status: str = "running") -> AgentTask:
    return AgentTask(
        title="Task",
        description="Task",
        query="Task",
        user_id=str(uuid4()),
        workspace_id=str(uuid4()),
        agent_id=uuid4(),
        status=status,
        execution_id=f"task-{uuid4()}",
        created_at=datetime.now(UTC),
    )


def _service(workflow_status: dict) -> TaskService:
    service = TaskService.__new__(TaskService)
    service.workflow_service = SimpleNamespace(
        get_workflow_status=AsyncMock(return_value=workflow_status)
    )
    return service


@pytest.mark.asyncio
async def test_failed_workflow_outcome_recovers_stale_running_task():
    task = _task()
    service = _service(
        {
            "execution_status": "completed",
            "status": "failed",
            "success": False,
            "failure_reason": "iteration_limit",
            "error": "Maximum iterations reached (10)",
        }
    )

    enriched = await service._enrich_task_with_workflow_status(task)

    assert enriched.status == "failed"
    assert enriched.error_message == "Maximum iterations reached (10)"


@pytest.mark.asyncio
async def test_live_temporal_status_does_not_downgrade_persisted_completion():
    task = _task(status="completed")
    service = _service({"execution_status": "running", "status": "running"})

    enriched = await service._enrich_task_with_workflow_status(task)

    assert enriched.status == "completed"
