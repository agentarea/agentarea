"""A paid reply that crosses a limit stays in the conversation; a refused call keeps its tool.call."""

from unittest.mock import MagicMock

from agentarea_execution.workflows import helpers
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_execution.workflows.helpers import EventManager
from agentarea_execution.workflows.models import ToolCall


def test_the_reply_that_crossed_the_budget_is_kept_and_its_calls_answered():
    run = AgentExecutionWorkflow()
    call = {"id": "c1", "type": "function", "function": {"name": "shell", "arguments": "{}"}}

    run._keep_reply({"role": "assistant", "content": "running it", "tool_calls": [call]})
    run._answer_unanswered_tool_calls("Not executed: the run stopped at a resource limit.")

    assert [m.role for m in run.state.messages] == ["assistant", "tool"]
    assert run.state.messages[0].tool_calls == [call]
    assert run.state.messages[1].tool_call_id == "c1"


def test_a_refused_call_is_announced_before_its_result(monkeypatch):
    monkeypatch.setattr(helpers.workflow, "logger", MagicMock())
    run = AgentExecutionWorkflow()
    run.event_manager = EventManager(task_id="t", agent_id="a", execution_id="e")
    call = ToolCall(id="c1", function={"name": "shell", "arguments": '{"cmd": "ls"}'})

    run._announce_tool_call(call)

    [event] = run._events.get_pending_events()
    assert event["data"]["tool_call_id"] == "c1"
    assert event["data"]["arguments"] == {"cmd": "ls"}
