"""The API reads an escalation's arguments through the workflow query that holds them."""

from types import SimpleNamespace

import pytest
from agentarea_agents.application.execution_service import ExecutionService, WorkflowNotFoundError
from agentarea_agents.application.temporal_workflow_service import TemporalWorkflowService
from agentarea_agents.infrastructure.temporal_orchestrator import TemporalWorkflowOrchestrator
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio import workflow
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

PENDING = [
    {
        "escalation_id": "esc-1",
        "tool_name": "shell",
        "tool_call_id": "call-1",
        "tool_args": {"command": "rm -rf build"},
        "approvers": [],
    }
]


class _Handle:
    def __init__(self, status: WorkflowExecutionStatus = WorkflowExecutionStatus.RUNNING):
        self.queries: list[str] = []
        self.status = status

    async def describe(self):
        return SimpleNamespace(status=self.status)

    async def query(self, name):
        self.queries.append(name)
        return PENDING


@pytest.mark.asyncio
async def test_pending_escalations_come_from_the_workflows_own_query():
    handle = _Handle()
    orchestrator = TemporalWorkflowOrchestrator(
        task_queue="test",
        max_concurrent_activities=1,
        max_concurrent_workflows=1,
    )
    orchestrator._client = SimpleNamespace(get_workflow_handle=lambda _: handle)
    service = TemporalWorkflowService(ExecutionService(orchestrator))

    assert await service.get_pending_escalations("task-1") == PENDING
    (query,) = handle.queries
    definition = workflow._Definition.must_from_class(AgentExecutionWorkflow)
    assert query in definition.queries


class _MissingWorkflowHandle:
    async def describe(self):
        raise RPCError("workflow not found for ID: task-1", RPCStatusCode.NOT_FOUND, b"")

    async def query(self, name):
        raise AssertionError("a missing workflow is never queried")


@pytest.mark.asyncio
async def test_a_run_without_a_workflow_is_reported_as_missing():
    orchestrator = TemporalWorkflowOrchestrator(
        task_queue="test",
        max_concurrent_activities=1,
        max_concurrent_workflows=1,
    )
    orchestrator._client = SimpleNamespace(get_workflow_handle=lambda _: _MissingWorkflowHandle())
    service = TemporalWorkflowService(ExecutionService(orchestrator))

    with pytest.raises(WorkflowNotFoundError):
        await service.get_pending_escalations("task-1")


@pytest.mark.asyncio
async def test_a_closed_run_waits_on_nothing_and_is_not_queried():
    handle = _Handle(WorkflowExecutionStatus.COMPLETED)
    orchestrator = TemporalWorkflowOrchestrator(
        task_queue="test",
        max_concurrent_activities=1,
        max_concurrent_workflows=1,
    )
    orchestrator._client = SimpleNamespace(get_workflow_handle=lambda _: handle)

    assert await orchestrator.get_workflow_pending_escalations("task-1") == []
    assert handle.queries == []
