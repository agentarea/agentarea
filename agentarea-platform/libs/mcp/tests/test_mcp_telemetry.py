"""The ``error.type`` an MCP client operation is counted under."""

from types import SimpleNamespace

from agentarea_mcp.telemetry import TOOL_ERROR, Operation, mcp_error_type
from mcp import MCPError


def test_an_mcp_error_is_its_json_rpc_code():
    assert mcp_error_type(MCPError(-32022, "unsupported protocol version")) == "-32022"


def test_any_other_failure_is_its_class():
    assert mcp_error_type(TimeoutError()) == "TimeoutError"


def test_a_tool_result_that_reports_an_error_is_a_tool_error():
    operation = Operation()
    result = SimpleNamespace(is_error=True)

    assert operation.result(result) is result
    assert operation.error_type == TOOL_ERROR


def test_a_successful_result_sets_no_error():
    operation = Operation()

    operation.result(SimpleNamespace(is_error=False))

    assert operation.error_type is None
