"""Terminal workflow failures must not surface raw Temporal exception text.

``get_workflow_status`` feeds ``TaskService._enrich_task_with_workflow_status``,
which copies ``error`` onto ``AgentTask.error_message``; that value is returned
by the task API. Raw Temporal failure text carries the whole cause chain,
including provider response bodies, so it must be classified here instead.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_agents.infrastructure.temporal_orchestrator import TemporalWorkflowOrchestrator


class _FailedHandle:
    def __init__(self, failure: Exception):
        self._failure = failure

    async def describe(self):
        return SimpleNamespace(
            status=SimpleNamespace(name="FAILED"),
            start_time=datetime.now(UTC),
            close_time=datetime.now(UTC),
            execution_time=timedelta(seconds=2),
        )

    async def result(self):
        raise self._failure


def _orchestrator(failure: Exception) -> TemporalWorkflowOrchestrator:
    orchestrator = TemporalWorkflowOrchestrator(
        temporal_address="localhost:7233",
        task_queue="test",
        max_concurrent_activities=1,
        max_concurrent_workflows=1,
    )
    orchestrator._client = SimpleNamespace(get_workflow_handle=lambda _: _FailedHandle(failure))
    return orchestrator


@pytest.mark.asyncio
async def test_failed_workflow_hides_raw_temporal_failure_text():
    leaked = f"provider rejected request: authorization=Bearer {uuid4()}"
    orchestrator = _orchestrator(RuntimeError(leaked))

    status = await orchestrator.get_workflow_status("task-1")

    assert status["status"] == "failed"
    assert status["success"] is False
    assert status["error"] == "Workflow execution failed"
    assert leaked not in str(status)


@pytest.mark.asyncio
async def test_failed_workflow_still_classifies_provider_quota():
    orchestrator = _orchestrator(RuntimeError("Insufficient balance for account acct-42"))

    status = await orchestrator.get_workflow_status("task-1")

    assert status["status"] == "blocked"
    assert status["error_type"] == "provider_quota_exceeded"
    assert status["error"] == "Provider quota exceeded"
    assert "acct-42" not in str(status)
