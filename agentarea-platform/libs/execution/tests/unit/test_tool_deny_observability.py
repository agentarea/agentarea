"""A policy denial must be visible in the event stream, not just in the logs.

Denial is a real outcome of a tool call the user watched start. Emitting it as
a failed `tool.result` keyed by tool_call_id lets the same supersede-by-id rule
resolve the tool part, so the UI shows a denied tool card instead of the call
silently vanishing.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from agentarea_execution.workflows import agent_execution_workflow as module
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_execution.workflows.constants import EventTypes


@pytest.fixture(autouse=True)
def _workflow_logger(monkeypatch):
    # workflow.logger needs the Temporal event loop; these tests run outside it.
    monkeypatch.setattr(module.workflow, "logger", MagicMock())


def _workflow() -> AgentExecutionWorkflow:
    wf = AgentExecutionWorkflow.__new__(AgentExecutionWorkflow)
    wf.state = SimpleNamespace(messages=[], current_iteration=3)
    emitted: list[tuple] = []
    # _events is a read-only property over event_manager.
    wf.event_manager = SimpleNamespace(
        add_event=lambda event_type, data: emitted.append((event_type, data))
    )
    wf._emitted = emitted
    return wf


def _tool_call(name: str = "shell") -> SimpleNamespace:
    return SimpleNamespace(id="tc-1", function={"name": name, "arguments": "{}"})


@pytest.mark.asyncio
async def test_denial_emits_a_failed_tool_result():
    wf = _workflow()

    await wf._deny_tool_call(_tool_call(), "shell", "not permitted by policy")

    assert len(wf._emitted) == 1
    event_type, data = wf._emitted[0]
    assert event_type == EventTypes.TOOL_CALL_COMPLETED
    assert data["success"] is False
    assert data["tool_name"] == "shell"
    assert data["tool_call_id"] == "tc-1"
    assert "not permitted by policy" in data["error"]


@pytest.mark.asyncio
async def test_event_carries_the_part_id_that_supersedes_the_tool_call():
    from agentarea_common.events.contract import derive_part

    wf = _workflow()
    await wf._deny_tool_call(_tool_call(), "shell", "not permitted by policy")

    _, data = wf._emitted[0]
    part = derive_part(EventTypes.TOOL_CALL_COMPLETED, data)
    assert part is not None
    assert part.part_id == "tc-1"
    assert part.kind == "tool"


@pytest.mark.asyncio
async def test_llm_still_sees_the_denial_message():
    wf = _workflow()

    await wf._deny_tool_call(_tool_call(), "shell", "not permitted by policy")

    assert len(wf.state.messages) == 1
    message = wf.state.messages[0]
    assert message.role == "tool"
    assert message.tool_call_id == "tc-1"
    assert "denied by policy" in message.content
