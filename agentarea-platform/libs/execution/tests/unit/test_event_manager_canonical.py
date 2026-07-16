"""EventManager emits the canonical dotted event vocabulary (emit-side seam).

The ``EventTypes`` constants hold canonical dotted names directly, so every
emitted + persisted event carries the canonical name and the wire speaks one
vocabulary. There is no legacy alias bridge.
"""

from __future__ import annotations

import logging

import pytest
from agentarea_execution.workflows.constants import EventTypes
from agentarea_execution.workflows.helpers import EventManager
from temporalio import workflow


@pytest.fixture(autouse=True)
def _plain_logger(monkeypatch):
    # ``add_event`` logs via ``workflow.logger``, which requires a live workflow
    # event loop. Swap in a plain logger so the emit-vocabulary logic runs under
    # a unit test without a Temporal sandbox.
    monkeypatch.setattr(workflow, "logger", logging.getLogger("test.event_manager"))


def _mgr() -> EventManager:
    return EventManager(task_id="t-1", agent_id="a-1", execution_id="e-1")


def _only_event(mgr: EventManager) -> dict:
    pending = mgr.get_pending_events()
    assert len(pending) == 1
    return pending[0]


def test_tool_call_completed_emits_tool_result():
    mgr = _mgr()
    mgr.add_event(EventTypes.TOOL_CALL_COMPLETED, {"tool_call_id": "tc-1", "tool_name": "shell"})
    assert _only_event(mgr)["event_type"] == "tool.result"


def test_tool_call_started_emits_tool_call():
    mgr = _mgr()
    mgr.add_event(EventTypes.TOOL_CALL_STARTED, {"tool_call_id": "tc-1"})
    assert _only_event(mgr)["event_type"] == "tool.call"


def test_llm_chunk_emits_dotted():
    mgr = _mgr()
    mgr.add_event(EventTypes.LLM_CALL_CHUNK, {"execution_id": "e-1", "iteration": 0})
    assert _only_event(mgr)["event_type"] == "llm.call.chunk"


def test_human_input_requested_emits_input_request():
    mgr = _mgr()
    mgr.add_event(EventTypes.HUMAN_INPUT_REQUESTED, {"input_request_id": "ir-1"})
    assert _only_event(mgr)["event_type"] == "input.request"


def test_workflow_completed_emits_task_completed_with_terminal_message():
    mgr = _mgr()
    mgr.add_event(EventTypes.WORKFLOW_COMPLETED, {"final_response": "All done."})
    event = _only_event(mgr)
    assert event["event_type"] == "task.completed"
    # Terminal message still fires after canonicalization.
    assert event["data"]["message"] == "All done."


def test_workflow_failed_emits_task_failed_with_reason():
    mgr = _mgr()
    mgr.add_event(EventTypes.WORKFLOW_FAILED, {"error": "boom"})
    event = _only_event(mgr)
    assert event["event_type"] == "task.failed"
    assert event["data"]["reason"] == "boom"
    assert event["data"]["message"]


def test_workflow_started_emits_task_started():
    mgr = _mgr()
    mgr.add_event(EventTypes.WORKFLOW_STARTED, {})
    assert _only_event(mgr)["event_type"] == "task.started"


def test_timeline_event_passes_through_unchanged():
    # System/timeline events not in the part taxonomy keep their legacy name.
    mgr = _mgr()
    mgr.add_event(EventTypes.BUDGET_WARNING, {"percentage": 80})
    assert _only_event(mgr)["event_type"] == "BudgetWarning"

    mgr2 = _mgr()
    mgr2.add_event(EventTypes.ITERATION_STARTED, {"iteration": 1})
    assert _only_event(mgr2)["event_type"] == "IterationStarted"


def test_base_task_fields_preserved():
    mgr = _mgr()
    mgr.add_event(EventTypes.TOOL_CALL_COMPLETED, {"tool_call_id": "tc-1"})
    data = _only_event(mgr)["data"]
    assert data["task_id"] == "t-1"
    assert data["agent_id"] == "a-1"
    assert data["execution_id"] == "e-1"


def test_event_types_constants_are_canonical():
    # Source constants speak the canonical dotted vocabulary directly.
    assert EventTypes.TOOL_CALL_STARTED == "tool.call"
    assert EventTypes.TOOL_CALL_COMPLETED == "tool.result"
    assert EventTypes.TOOL_CALL_FAILED == "tool.result"
    assert EventTypes.LLM_CALL_STARTED == "llm.call.started"
    assert EventTypes.LLM_CALL_CHUNK == "llm.call.chunk"
    assert EventTypes.LLM_CALL_COMPLETED == "llm.call.completed"
    assert EventTypes.LLM_CALL_FAILED == "llm.call.failed"
    assert EventTypes.HUMAN_INPUT_REQUESTED == "input.request"
    assert EventTypes.HUMAN_INPUT_RECEIVED == "input.response"
    assert EventTypes.HUMAN_APPROVAL_REQUESTED == "approval.request"
    assert EventTypes.HUMAN_APPROVAL_RECEIVED == "approval.response"
    assert EventTypes.HUMAN_APPROVAL_DENIED == "approval.response"
    assert EventTypes.WORKFLOW_STARTED == "task.started"
    assert EventTypes.WORKFLOW_COMPLETED == "task.completed"
    assert EventTypes.WORKFLOW_FAILED == "task.failed"
    assert EventTypes.WORKFLOW_CANCELLED == "task.cancelled"


def test_timeline_constants_stay_bare():
    # Timeline/system events are not in the part taxonomy; keep bare names.
    assert EventTypes.BUDGET_WARNING == "BudgetWarning"
    assert EventTypes.ITERATION_STARTED == "IterationStarted"
    assert EventTypes.MODEL_CHANGED == "ModelChanged"
    assert EventTypes.WORKFLOW_CONTINUED_AS_NEW == "WorkflowContinuedAsNew"
