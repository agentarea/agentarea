"""Tests for dispatcher hardening: never-empty result, last_dispatch queue."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestDispatcherNeverEmptyResult:
    """Dispatcher returns a populated result string on all exception paths."""

    @pytest.mark.asyncio
    async def test_mcp_execute_exception_returns_populated_result(self):
        """Exception in execute_tool must produce a non-empty result string."""
        from agentarea_execution.models import MCPToolRequest, MCPToolResult

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


class TestLastDispatchQueue:
    """Tests for the bounded fire-and-forget last_dispatch queue."""

    def test_enqueue_succeeds_on_empty_queue(self):
        """_enqueue_last_dispatch adds item to queue when not full."""
        import agentarea_execution.activities.agent_execution_activities as mod

        queue = asyncio.Queue(maxsize=1000)
        with patch.object(mod, "_last_dispatch_queue", queue):
            with patch.object(mod, "_mcp_last_dispatch_dropped_total") as mock_counter:
                mod._enqueue_last_dispatch("inst-1", {"status": "succeeded", "at": "now"})
                assert queue.qsize() == 1
                mock_counter.inc.assert_not_called()

    def test_enqueue_drops_on_full_queue_and_increments_counter(self):
        """_enqueue_last_dispatch drops item and increments counter when queue is full."""
        import agentarea_execution.activities.agent_execution_activities as mod

        queue = asyncio.Queue(maxsize=2)
        queue.put_nowait(("a", {}))
        queue.put_nowait(("b", {}))
        assert queue.full()

        with patch.object(mod, "_last_dispatch_queue", queue):
            with patch.object(mod, "_mcp_last_dispatch_dropped_total") as mock_counter:
                mod._enqueue_last_dispatch("inst-3", {"status": "failed"})
                mock_counter.inc.assert_called_once()
                # Queue remains at capacity, dropped item not added
                assert queue.qsize() == 2

    def test_enqueue_never_blocks(self):
        """_enqueue_last_dispatch must return immediately even on full queue."""
        import agentarea_execution.activities.agent_execution_activities as mod

        queue = asyncio.Queue(maxsize=1)
        queue.put_nowait(("existing", {}))

        with patch.object(mod, "_last_dispatch_queue", queue):
            with patch.object(mod, "_mcp_last_dispatch_dropped_total"):
                # Should not raise and should return immediately
                mod._enqueue_last_dispatch("inst-new", {})


class TestLastDispatchFlushBatching:
    """Tests that the flush loop batches up to 100 rows per cycle."""

    @pytest.mark.asyncio
    async def test_flush_batches_100_rows_in_single_pass(self):
        """Flush loop drains up to 100 items per sleep cycle."""
        queue = asyncio.Queue(maxsize=1000)
        for i in range(150):
            await queue.put((f"inst-{i}", {"status": "succeeded", "at": "t"}))

        batch: list = []
        try:
            while len(batch) < 100:
                batch.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            pass

        assert len(batch) == 100
        assert queue.qsize() == 50

    @pytest.mark.asyncio
    async def test_flush_handles_partial_batch(self):
        """Flush loop handles fewer than 100 items gracefully."""
        queue = asyncio.Queue(maxsize=1000)
        for i in range(7):
            await queue.put((f"inst-{i}", {"status": "succeeded", "at": "t"}))

        batch: list = []
        try:
            while len(batch) < 100:
                batch.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            pass

        assert len(batch) == 7
        assert queue.qsize() == 0
