import json
from unittest.mock import AsyncMock

import pytest
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_governance.domain.tool_calls import CONTROL_FLOW_TOOL_NAMES
from agentarea_execution.workflows.models import ToolCall


def _call(name: str, call_id: str) -> ToolCall:
    arguments = {"result": "done", "artifacts": []} if name == "completion" else {}
    return ToolCall(
        id=call_id,
        function={"name": name, "arguments": json.dumps(arguments)},
    )


def _workflow(*, used: int = 0, total: int = 1) -> AgentExecutionWorkflow:
    instance = AgentExecutionWorkflow()
    instance.state.tool_calls_used = used
    instance.state.effective_policy = {
        "execution": {
            "max_tool_calls_per_turn": 1,
            "max_tool_calls_total": total,
        }
    }
    instance._execute_mcp_tool = AsyncMock()
    instance._handle_task_completion = AsyncMock()
    return instance


@pytest.mark.asyncio
async def test_completion_does_not_consume_tool_call_budget() -> None:
    instance = _workflow(used=1, total=1)
    completion = _call("completion", "completion-1")

    await instance._execute_tool_calls([completion])

    assert instance.state.tool_calls_used == 1
    instance._handle_task_completion.assert_awaited_once_with(completion)


@pytest.mark.asyncio
async def test_completion_is_excluded_from_per_turn_capability_count() -> None:
    instance = _workflow(total=1)
    regular = _call("shell", "shell-1")
    completion = _call("completion", "completion-1")

    await instance._execute_tool_calls([regular, completion])

    assert instance.state.tool_calls_used == 1
    instance._execute_mcp_tool.assert_awaited_once_with(regular)
    instance._handle_task_completion.assert_awaited_once_with(completion)


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", sorted(CONTROL_FLOW_TOOL_NAMES))
async def test_no_control_flow_tool_consumes_tool_call_budget(tool_name: str) -> None:
    """Budget classification must use the same canonical set disclosure uses."""
    instance = _workflow(used=1, total=1)
    instance._execute_request_user_input = AsyncMock()
    instance._execute_recall_history = AsyncMock()
    instance._execute_read_tool_output = AsyncMock()
    instance._execute_activate_tool_source = AsyncMock()
    instance._execute_load_tools = AsyncMock()

    await instance._execute_tool_calls([_call(tool_name, f"{tool_name}-1")])

    assert instance.state.tool_calls_used == 1


@pytest.mark.asyncio
async def test_capability_tool_still_consumes_exhausted_budget() -> None:
    instance = _workflow(used=1, total=1)

    with pytest.raises(Exception, match="tool-call budget exceeded"):
        await instance._execute_tool_calls([_call("shell", "shell-1")])

    instance._execute_mcp_tool.assert_not_awaited()
