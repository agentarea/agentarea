"""The tool activity outlives every MCP tool call it may be waiting on."""

from datetime import timedelta

from agentarea_execution.workflows.constants import TOOL_EXECUTION_TIMEOUT
from agentarea_mcp.application.mcp_client import GATEWAY_START_WAIT_SECONDS
from agentarea_mcp.tool_timeout import MAX_TOOL_TIMEOUT_SECONDS, TOOL_TIMEOUT_GRACE_SECONDS


def test_the_activity_budget_covers_the_longest_call_after_a_cold_start():
    longest_call = timedelta(
        seconds=GATEWAY_START_WAIT_SECONDS + MAX_TOOL_TIMEOUT_SECONDS + TOOL_TIMEOUT_GRACE_SECONDS
    )
    assert TOOL_EXECUTION_TIMEOUT > longest_call
