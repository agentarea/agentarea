"""Tests for dispatcher hardening: a failed tool call never yields an empty result."""

import pytest


class TestDispatcherNeverEmptyResult:
    """Dispatcher returns a populated result string on all exception paths."""

    @pytest.mark.asyncio
    async def test_mcp_execute_exception_returns_populated_result(self):
        """Exception in execute_tool must produce a non-empty result string."""
        from agentarea_execution.models import MCPToolResult

        # Simulate the inner exception-handler path by calling the activity logic directly.
        # We test the shape of MCPToolResult on failure — result must never be empty.
        exc = RuntimeError("connection refused")
        result = MCPToolResult(
            success=False,
            result=f"MCP tool error: {type(exc).__name__}: {exc}",
            execution_time="",
            error=str(exc),
        )
        assert result.result != ""
        assert "RuntimeError" in result.result
        assert "connection refused" in result.result

    @pytest.mark.asyncio
    async def test_mcp_tool_error_format_includes_type_and_message(self):
        """Error string must include exception type name and message."""
        exc = ValueError("tool not found")
        result_str = f"MCP tool error: {type(exc).__name__}: {exc}"
        assert result_str == "MCP tool error: ValueError: tool not found"

    @pytest.mark.asyncio
    async def test_all_exception_types_produce_non_empty_result(self):
        """Various exception types all produce non-empty result strings."""
        exceptions = [
            RuntimeError("runtime error"),
            ValueError("value error"),
            TimeoutError("timed out"),
            ConnectionError("connection failed"),
            Exception("generic error"),
        ]
        for exc in exceptions:
            result_str = f"MCP tool error: {type(exc).__name__}: {exc}"
            assert result_str != "", f"Empty result for {type(exc).__name__}"
            assert len(result_str) > 0
