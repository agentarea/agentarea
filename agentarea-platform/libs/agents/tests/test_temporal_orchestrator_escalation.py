"""Resolving an escalation must target one the workflow is waiting on, as one of its approvers.

The workflow's ``resolve_escalation`` signal drops ids it does not know and
callers who are not approvers, so a signal that "succeeded" says nothing about
whether anything was resolved. Both are checked against the workflow's own
pending escalations before signalling.
"""

from types import SimpleNamespace

import pytest
from agentarea_agents.application.execution_service import (
    EscalationNotPendingError,
    ExecutionService,
    NotAnApproverError,
)
from agentarea_agents.application.temporal_workflow_service import TemporalWorkflowService
from agentarea_agents.infrastructure.temporal_orchestrator import TemporalWorkflowOrchestrator
from temporalio.service import RPCError, RPCStatusCode


class _Handle:
    def __init__(self, pending=None, query_error: Exception | None = None):
        self._pending = pending or []
        self._query_error = query_error
        self.signals: list = []

    async def query(self, name):
        assert name == "get_pending_escalations"
        if self._query_error is not None:
            raise self._query_error
        return self._pending

    async def signal(self, name, args):
        self.signals.append((name, args))


def _orchestrator(handle: _Handle) -> TemporalWorkflowOrchestrator:
    orchestrator = TemporalWorkflowOrchestrator(
        temporal_address="localhost:7233",
        task_queue="test",
        max_concurrent_activities=1,
        max_concurrent_workflows=1,
    )
    orchestrator._client = SimpleNamespace(get_workflow_handle=lambda _: handle)
    return orchestrator


def _pending(escalation_id: str = "esc-1", approvers: list[str] | None = None) -> dict:
    return {
        "escalation_id": escalation_id,
        "tool_name": "shell",
        "tool_call_id": "call-1",
        "tool_args": {"command": "rm -rf build"},
        "approvers": approvers or [],
    }


@pytest.mark.asyncio
async def test_unknown_escalation_is_rejected_without_signalling():
    handle = _Handle([_pending("esc-1")])

    with pytest.raises(EscalationNotPendingError):
        await _orchestrator(handle).resolve_escalation_workflow("task-1", "None", True)

    assert handle.signals == []


@pytest.mark.asyncio
async def test_already_resolved_escalation_is_rejected():
    # The query lists only unresolved escalations; a resolved one is simply absent.
    handle = _Handle([])

    with pytest.raises(EscalationNotPendingError):
        await _orchestrator(handle).resolve_escalation_workflow("task-1", "esc-1", True)

    assert handle.signals == []


@pytest.mark.asyncio
async def test_missing_workflow_has_no_pending_escalation():
    handle = _Handle(
        query_error=RPCError("workflow not found for ID: task-1", RPCStatusCode.NOT_FOUND, b"")
    )

    with pytest.raises(EscalationNotPendingError):
        await _orchestrator(handle).resolve_escalation_workflow("task-1", "esc-1", True)

    assert handle.signals == []


@pytest.mark.asyncio
async def test_an_error_that_merely_says_not_found_is_not_a_missing_workflow():
    handle = _Handle(query_error=RuntimeError("query handler: resource not found"))

    resolved = await _orchestrator(handle).resolve_escalation_workflow("task-1", "esc-1", True)

    assert resolved is False
    assert handle.signals == []


@pytest.mark.asyncio
async def test_a_caller_who_is_not_an_approver_is_refused_without_signalling():
    handle = _Handle([_pending("esc-1", approvers=["user:security-lead"])])

    with pytest.raises(NotAnApproverError):
        await _orchestrator(handle).resolve_escalation_workflow(
            "task-1", "esc-1", True, "", "user-1"
        )

    assert handle.signals == []


@pytest.mark.asyncio
async def test_pending_escalation_is_signalled():
    handle = _Handle([_pending("esc-1")])

    resolved = await _orchestrator(handle).resolve_escalation_workflow(
        "task-1", "esc-1", False, "no", "user-1"
    )

    assert resolved is True
    assert handle.signals == [("resolve_escalation", ["esc-1", False, "no", "user-1"])]


@pytest.mark.asyncio
async def test_a_designated_approver_is_signalled():
    handle = _Handle([_pending("esc-1", approvers=["user:user-1"])])

    assert await _orchestrator(handle).resolve_escalation_workflow(
        "task-1", "esc-1", True, "", "user-1"
    )
    assert handle.signals == [("resolve_escalation", ["esc-1", True, "", "user-1"])]


@pytest.mark.asyncio
async def test_workflow_service_does_not_flatten_not_pending_into_failure():
    handle = _Handle([])
    service = TemporalWorkflowService(ExecutionService(_orchestrator(handle)))

    with pytest.raises(EscalationNotPendingError):
        await service.resolve_escalation("task-1", "None", True)


@pytest.mark.asyncio
async def test_workflow_service_does_not_flatten_not_an_approver_into_failure():
    handle = _Handle([_pending("esc-1", approvers=["user:security-lead"])])
    service = TemporalWorkflowService(ExecutionService(_orchestrator(handle)))

    with pytest.raises(NotAnApproverError):
        await service.resolve_escalation("task-1", "esc-1", True, "", "user-1")
