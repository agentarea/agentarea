"""Wiring tests: every capability dispatch branch goes through the single PEP.

These assert the *wiring* (each branch calls `_gate_tool_call` and aborts when
policy denies), complementing test_tool_policy_decision.py which covers the
decision *logic*. The workflow instance is built via __new__ so no Temporal
runtime is needed — the gate is the first thing each branch touches, so a
denied gate returns before any activity/child-workflow call.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow

# The capability branches that must enforce policy. Control primitives
# (completion, user-input, recall, read_output, activate_source, load_tools)
# are intentionally exempt and not listed here. Sandbox execution is not a
# branch of its own: it is the shell tool, gated via _execute_mcp_tool.
CAPABILITY_BRANCHES = [
    "_execute_mcp_tool",
    "_execute_agent_delegation",
    "_execute_skill_activation",
]


def _workflow() -> AgentExecutionWorkflow:
    # Bypass __init__: we only exercise the early gate path.
    return AgentExecutionWorkflow.__new__(AgentExecutionWorkflow)


def _tool_call(name: str = "shell") -> SimpleNamespace:
    return SimpleNamespace(id="tc-1", function={"name": name, "arguments": "{}"})


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", CAPABILITY_BRANCHES)
async def test_branch_calls_gate_and_aborts_on_deny(method_name):
    wf = _workflow()
    wf._gate_tool_call = AsyncMock(return_value=False)
    tool_call = _tool_call()

    if method_name == "_execute_agent_delegation":
        result = await getattr(wf, method_name)(tool_call, run_budget_usd=1)
    else:
        result = await getattr(wf, method_name)(tool_call)

    # Denied -> branch returns without touching any downstream executor.
    assert result is None
    wf._gate_tool_call.assert_awaited_once_with(tool_call)
