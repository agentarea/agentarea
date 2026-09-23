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
@pytest.mark.parametrize(
    "business_status",
    [
        "waiting_for_input",
        "waiting_for_approval",
        "waiting_for_continuation",
        "completed",
        "blocked",
    ],
)
async def test_live_execution_preserves_business_status(business_status):
    task = _task(status=business_status)
    service = _service({"execution_status": "running", "status": "running"})

    enriched = await service._enrich_task_with_workflow_status(task)

    assert enriched.status == business_status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome",
    [
        "waiting_for_input",
        "waiting_for_approval",
        "waiting_for_continuation",
        "completed",
        "blocked",
    ],
)
async def test_closed_execution_recovers_business_outcome(outcome):
    task = _task()
    result = {"status": outcome, "response": "Task outcome"}
    service = _service({"execution_status": "completed", "status": outcome, "result": result})

    enriched = await service._enrich_task_with_workflow_status(task)

    assert enriched.status == outcome
    assert enriched.result == result


@pytest.mark.asyncio
@pytest.mark.parametrize("business_status", ["waiting_for_input", "blocked", "failed", "completed"])
async def test_engine_completion_without_business_outcome_preserves_task(business_status):
    task = _task(status=business_status)
    task.result = {"response": "Persisted outcome"}
    service = _service({"execution_status": "completed", "status": "completed", "result": None})

    enriched = await service._enrich_task_with_workflow_status(task)

    assert enriched.status == business_status
    assert enriched.result == {"response": "Persisted outcome"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("execution_status", "outcome"),
    [
        ("failed", "failed"),
        ("cancelled", "cancelled"),
        ("canceled", "cancelled"),
        ("failed", "blocked"),
    ],
)
async def test_execution_failure_reconciles_waiting_task(execution_status, outcome):
    service = _service(
        {"execution_status": execution_status, "status": outcome, "error": "Execution stopped"}
    )

    enriched = await service._enrich_task_with_workflow_status(_task("waiting_for_input"))

    assert enriched.status == outcome
    assert enriched.error_message == "Execution stopped"


@pytest.mark.asyncio
async def test_business_result_overrides_engine_completion():
    result = {"status": "blocked", "response": "Required credentials are unavailable"}
    service = _service({"execution_status": "completed", "status": "completed", "result": result})

    enriched = await service._enrich_task_with_workflow_status(_task())

    assert enriched.status == "blocked"
    assert enriched.result == result
