"""Workflow handler for `load_tools` meta-tool (issue #115).

Direct-instance tests on `AgentExecutionWorkflow` — no Temporal harness needed.
Exercises the post-discovery state shape and the load_tools dispatch path.
"""

import json
from unittest.mock import MagicMock

import pytest

from agentarea_agents_sdk.tools.disclosure import NamedLookupPolicy
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_execution.workflows.models import ToolCall


def _make_pool(num: int):
    pool = []
    for i in range(num):
        name = f"op_{i:02d}"
        pool.append(
            {
                "name": name,
                "description": f"Operation {i}",
                "connection_id": "stripe-conn",
                "schema": {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": f"Operation {i}",
                        "parameters": {"type": "object", "properties": {}},
                    },
                },
                "source_type": "openapi",
            }
        )
    return pool


def _wf_with_pool(num_ops: int = 50):
    wf = AgentExecutionWorkflow()
    # Disclosure budgets the revealed schemas against the model's context
    # window, so the state has to carry one the way a real run's does.
    wf.state.context_window = 128000
    wf.state.searchable_tool_pool = _make_pool(num_ops)
    wf.state.available_tools = [
        {"type": "function", "function": {"name": "completion", "parameters": {}}},
    ]
    wf._disclosure_policy = NamedLookupPolicy()
    wf.event_manager = MagicMock()
    return wf


def _call(name: str, args: dict, call_id: str = "tc_1"):
    return ToolCall(
        id=call_id,
        function={"name": name, "arguments": json.dumps(args)},
    )


@pytest.mark.asyncio
async def test_load_tools_reveals_requested_schemas():
    wf = _wf_with_pool(50)
    await wf._execute_load_openapi_tools(_call("load_tools", {"tool_names": ["op_05", "op_42"]}))

    revealed_names = [
        t["function"]["name"]
        for t in wf.state.available_tools
        if t["function"]["name"].startswith("op_")
    ]
    assert set(revealed_names) == {"op_05", "op_42"}
    assert wf.state.revealed_openapi_tools == ["op_05", "op_42"]


@pytest.mark.asyncio
async def test_load_tools_unknown_name_does_not_pollute_state():
    wf = _wf_with_pool(10)
    await wf._execute_load_openapi_tools(
        _call("load_tools", {"tool_names": ["op_00", "nonexistent"]})
    )
    op_names = [
        t["function"]["name"]
        for t in wf.state.available_tools
        if t["function"]["name"].startswith("op_")
    ]
    assert op_names == ["op_00"]
    assert wf.state.revealed_openapi_tools == ["op_00"]
    # Tool message reports the unknown one
    last_msg = wf.state.messages[-1]
    assert "nonexistent" in last_msg.content


@pytest.mark.asyncio
async def test_load_tools_dedupes_repeat_reveal():
    wf = _wf_with_pool(5)
    await wf._execute_load_openapi_tools(_call("load_tools", {"tool_names": ["op_01"]}))
    await wf._execute_load_openapi_tools(_call("load_tools", {"tool_names": ["op_01"]}, "tc_2"))
    op_names = [
        t["function"]["name"]
        for t in wf.state.available_tools
        if t["function"]["name"].startswith("op_")
    ]
    assert op_names == ["op_01"]
    assert wf.state.revealed_openapi_tools == ["op_01"]


@pytest.mark.asyncio
async def test_load_tools_with_no_pool_returns_error_message():
    wf = AgentExecutionWorkflow()
    wf.event_manager = MagicMock()
    await wf._execute_load_openapi_tools(_call("load_tools", {"tool_names": ["x"]}))
    assert wf.state.available_tools == []
    last_msg = wf.state.messages[-1]
    assert "no searchable" in last_msg.content.lower()


@pytest.mark.asyncio
async def test_load_tools_emits_tool_call_completed_event():
    wf = _wf_with_pool(3)
    await wf._execute_load_openapi_tools(_call("load_tools", {"tool_names": ["op_00", "missing"]}))
    args, _ = wf.event_manager.add_event.call_args
    event_type, payload = args
    assert payload["tool_name"] == "load_tools"
    assert payload["matched_names"] == ["op_00"]
    assert payload["unknown_names"] == ["missing"]


@pytest.mark.asyncio
async def test_load_tools_handles_malformed_arguments():
    wf = _wf_with_pool(3)
    bad_call = ToolCall(
        id="tc_bad",
        function={"name": "load_tools", "arguments": "not json"},
    )
    await wf._execute_load_openapi_tools(bad_call)
    # No reveals, no crash; message indicates nothing happened.
    assert wf.state.revealed_openapi_tools == []
    assert all(
        not t["function"]["name"].startswith("op_") for t in wf.state.available_tools
    )


@pytest.mark.asyncio
async def test_load_tools_non_list_argument_treated_as_empty():
    wf = _wf_with_pool(3)
    await wf._execute_load_openapi_tools(_call("load_tools", {"tool_names": "op_00"}))
    assert wf.state.revealed_openapi_tools == []
