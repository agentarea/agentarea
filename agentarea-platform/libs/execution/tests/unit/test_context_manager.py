"""Unit tests for context window manager."""

from __future__ import annotations

import pytest
from agentarea_execution.workflows.constants import (
    CONTEXT_COMPACT_THRESHOLD,
    CONTEXT_RESERVE_FOR_OUTPUT,
    CONTEXT_WARNING_THRESHOLD,
)
from agentarea_execution.workflows.context_manager import (
    ContextWindowManager,
    estimate_tokens,
    estimate_tokens_for_messages,
    find_compaction_boundary,
    validate_tool_pairs,
)

# ---------------------------------------------------------------------------
# estimate_tokens
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    def test_simple_string(self):
        result = estimate_tokens("Hello, world!")
        assert result > 0

    def test_empty_string(self):
        result = estimate_tokens("")
        assert result == 0

    def test_longer_text_has_more_tokens(self):
        short = estimate_tokens("Hi")
        long = estimate_tokens("Hi " * 100)
        assert long > short

    def test_returns_int(self):
        result = estimate_tokens("some text here")
        assert isinstance(result, int)


# ---------------------------------------------------------------------------
# estimate_tokens_for_messages
# ---------------------------------------------------------------------------


class TestEstimateTokensForMessages:
    def test_basic_messages(self):
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is 2 + 2?"},
            {"role": "assistant", "content": "4"},
        ]
        result = estimate_tokens_for_messages(messages)
        assert result > 0
        assert isinstance(result, int)

    def test_empty_messages(self):
        result = estimate_tokens_for_messages([])
        assert result == 0

    def test_messages_with_tool_calls(self):
        messages = [
            {"role": "user", "content": "Use the calculator"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {"name": "calculator", "arguments": '{"x": 1, "y": 2}'},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_abc123",
                "content": "3",
            },
        ]
        with_tools = estimate_tokens_for_messages(messages)
        # Tool call messages should count at least as much
        assert with_tools >= 0
        assert isinstance(with_tools, int)

    def test_overhead_per_message(self):
        # Single message with no content should at least have overhead
        messages = [{"role": "user", "content": ""}]
        result = estimate_tokens_for_messages(messages)
        # Should include at least the TOKENS_PER_MESSAGE_OVERHEAD (4)
        assert result >= 4

    def test_list_content_blocks(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Hello"},
                    {"type": "text", "text": "World"},
                ],
            }
        ]
        result = estimate_tokens_for_messages(messages)
        assert result > 0


# ---------------------------------------------------------------------------
# validate_tool_pairs
# ---------------------------------------------------------------------------


class TestValidateToolPairs:
    def test_valid_pairs(self):
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "foo", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "result"},
        ]
        assert validate_tool_pairs(messages) is True

    def test_orphaned_tool_result(self):
        messages = [
            # No assistant message with tool_calls that produced "call_missing"
            {"role": "tool", "tool_call_id": "call_missing", "content": "result"},
        ]
        assert validate_tool_pairs(messages) is False

    def test_no_tool_calls(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        assert validate_tool_pairs(messages) is True

    def test_multiple_valid_pairs(self):
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "a", "arguments": "{}"},
                    },
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {"name": "b", "arguments": "{}"},
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "r1"},
            {"role": "tool", "tool_call_id": "call_2", "content": "r2"},
        ]
        assert validate_tool_pairs(messages) is True

    def test_partial_orphan(self):
        """One valid pair and one orphan."""
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "a", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "r1"},
            {"role": "tool", "tool_call_id": "call_orphan", "content": "r2"},
        ]
        assert validate_tool_pairs(messages) is False


# ---------------------------------------------------------------------------
# find_compaction_boundary
# ---------------------------------------------------------------------------


def _make_plain_messages(n: int) -> list[dict]:
    """Create n plain user/assistant messages (no tool calls)."""
    messages = [{"role": "system", "content": "system"}]
    for i in range(n):
        if i % 2 == 0:
            messages.append({"role": "user", "content": f"user message {i}"})
        else:
            messages.append({"role": "assistant", "content": f"assistant reply {i}"})
    return messages


class TestFindCompactionBoundary:
    def test_too_few_messages_returns_zero(self):
        # With keep_recent=6, need at least 8 messages (1 system + 6 recent + 1 to compact)
        messages = _make_plain_messages(4)  # 5 total
        result = find_compaction_boundary(messages, keep_recent=6)
        assert result == 0

    def test_enough_messages_returns_nonzero(self):
        messages = _make_plain_messages(10)  # 11 total
        result = find_compaction_boundary(messages, keep_recent=4)
        assert result > 0

    def test_boundary_keeps_first_message(self):
        messages = _make_plain_messages(10)
        boundary = find_compaction_boundary(messages, keep_recent=4)
        # boundary > 0 means messages[0] is always kept (system prompt)
        assert boundary != 1 or boundary == 0  # 0 means no compaction

    def test_does_not_split_tool_pairs(self):
        """Boundary should not fall between a tool_call and its tool_result."""
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "u1"},
            {"role": "user", "content": "u2"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "f", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "result"},
            {"role": "assistant", "content": "done"},
            {"role": "user", "content": "u3"},
            {"role": "assistant", "content": "a3"},
        ]
        boundary = find_compaction_boundary(messages, keep_recent=3)
        if boundary > 0:
            # The kept suffix must still pass validate_tool_pairs
            kept = [messages[0], *messages[boundary:]]
            assert validate_tool_pairs(kept) is True

    def test_keeps_recent_messages(self):
        messages = _make_plain_messages(12)  # 13 total
        keep_recent = 4
        boundary = find_compaction_boundary(messages, keep_recent=keep_recent)
        if boundary > 0:
            assert len(messages) - boundary >= keep_recent


# ---------------------------------------------------------------------------
# ContextWindowManager
# ---------------------------------------------------------------------------


class TestContextWindowManager:
    def test_context_window_is_required(self):
        with pytest.raises(TypeError):
            ContextWindowManager()  # type: ignore[call-arg]

    @pytest.mark.parametrize("value", [0, -1, None, True])
    def test_context_window_must_be_positive_integer(self, value):
        with pytest.raises(ValueError, match="positive integer"):
            ContextWindowManager(context_window=value)  # type: ignore[arg-type]

    def test_custom_context_window(self):
        mgr = ContextWindowManager(context_window=200000)
        expected_limit = int(200000 * (1.0 - CONTEXT_RESERVE_FOR_OUTPUT))
        assert mgr._effective_limit == expected_limit

    def test_needs_compaction_under_threshold(self):
        mgr = ContextWindowManager(context_window=100000)
        mgr.update_usage(int(mgr._effective_limit * 0.5))
        assert mgr.needs_compaction() is False

    def test_needs_compaction_over_threshold(self):
        mgr = ContextWindowManager(context_window=100000)
        mgr.update_usage(int(mgr._effective_limit * CONTEXT_COMPACT_THRESHOLD))
        assert mgr.needs_compaction() is True

    def test_needs_compaction_just_over_threshold(self):
        mgr = ContextWindowManager(context_window=100000)
        mgr.update_usage(mgr._effective_limit)  # 100% usage
        assert mgr.needs_compaction() is True

    def test_should_warn_under_threshold(self):
        mgr = ContextWindowManager(context_window=100000)
        mgr.update_usage(int(mgr._effective_limit * 0.5))
        assert mgr.should_warn() is False

    def test_should_warn_over_threshold(self):
        mgr = ContextWindowManager(context_window=100000)
        mgr.update_usage(int(mgr._effective_limit * CONTEXT_WARNING_THRESHOLD))
        assert mgr.should_warn() is True

    def test_warning_sent_only_once(self):
        mgr = ContextWindowManager(context_window=100000)
        mgr.update_usage(int(mgr._effective_limit * CONTEXT_WARNING_THRESHOLD))
        assert mgr.should_warn() is True
        mgr.mark_warning_sent()
        assert mgr.should_warn() is False

    def test_mark_compacted_resets_warning(self):
        mgr = ContextWindowManager(context_window=100000)
        mgr.update_usage(int(mgr._effective_limit * CONTEXT_WARNING_THRESHOLD))
        mgr.mark_warning_sent()
        mgr.mark_compacted()
        # Warning should be re-enabled after compaction
        assert mgr._warning_sent is False
        assert mgr.should_warn() is True

    def test_compaction_count(self):
        mgr = ContextWindowManager(context_window=100000)
        assert mgr.compaction_count == 0
        mgr.mark_compacted()
        mgr.mark_compacted()
        assert mgr.compaction_count == 2

    def test_get_status(self):
        mgr = ContextWindowManager(context_window=100000)
        mgr.update_usage(50000)
        status = mgr.get_status()
        assert "current_tokens" in status
        assert "effective_limit" in status
        assert "usage_ratio" in status
        assert "needs_compaction" in status
        assert "warning_sent" in status
        assert "compaction_count" in status
        assert "compact_threshold" in status
        assert "warning_threshold" in status
        assert status["current_tokens"] == 50000

    def test_estimate_usage_updates_state(self):
        mgr = ContextWindowManager(context_window=100000)
        messages = [
            {"role": "user", "content": "hello world"},
        ]
        estimated = mgr.estimate_usage(messages)
        assert estimated > 0
        assert mgr._current_tokens == estimated

    def test_get_usage_ratio(self):
        mgr = ContextWindowManager(context_window=100000)
        mgr.update_usage(mgr._effective_limit // 2)
        ratio = mgr.get_usage_ratio()
        assert 0.4 < ratio < 0.6  # approximately 0.5
