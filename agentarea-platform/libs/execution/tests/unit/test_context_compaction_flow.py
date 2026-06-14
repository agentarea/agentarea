"""Tests for context compaction integration flow.

Tests the full compaction lifecycle: large conversations triggering compaction,
boundary preservation, tool pair safety, multiple compactions, orphan repair.
"""


from agentarea_execution.workflows.context_manager import (
    ContextWindowManager,
    estimate_tokens_for_messages,
    find_compaction_boundary,
    validate_tool_pairs,
)


def _make_conversation(num_turns: int, content_size: int = 500) -> list[dict]:
    """Generate a synthetic conversation with tool calls."""
    messages = [
        {"role": "system", "content": "You are a helpful agent."},
        {"role": "user", "content": "Please help me with a complex task."},
    ]
    for i in range(num_turns):
        # Assistant with tool call
        messages.append(
            {
                "role": "assistant",
                "content": f"Step {i}: I'll use a tool. " + "x" * content_size,
                "tool_calls": [
                    {
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {
                            "name": f"tool_{i}",
                            "arguments": '{"key": "value"}',
                        },
                    }
                ],
            }
        )
        # Tool result
        messages.append(
            {
                "role": "tool",
                "content": f"Result for step {i}: " + "data " * (content_size // 5),
                "tool_call_id": f"call_{i}",
                "name": f"tool_{i}",
            }
        )
    # Final assistant response
    messages.append({"role": "assistant", "content": "I've completed the analysis."})
    return messages


def _make_plain_conversation(num_turns: int, content_size: int = 500) -> list[dict]:
    """Generate a conversation without tool calls."""
    messages = [
        {"role": "system", "content": "You are a helpful agent."},
        {"role": "user", "content": "Help me write a story."},
    ]
    for i in range(num_turns):
        messages.append(
            {
                "role": "assistant",
                "content": f"Chapter {i}: " + "narrative " * (content_size // 10),
            }
        )
        messages.append(
            {
                "role": "user",
                "content": f"Continue with chapter {i + 1}. " + "details " * 20,
            }
        )
    return messages


class TestCompactionFlowTriggering:
    """Test that compaction triggers at the right time."""

    def test_large_conversation_triggers_compaction(self):
        """A long conversation should trigger compaction."""
        messages = _make_conversation(20, content_size=1000)
        mgr = ContextWindowManager(context_window=8000)
        tokens = mgr.estimate_usage(messages)
        mgr.update_usage(tokens)
        assert mgr.needs_compaction() is True

    def test_small_conversation_no_compaction(self):
        """Short conversations should not need compaction."""
        messages = _make_conversation(2, content_size=100)
        mgr = ContextWindowManager(context_window=200000)
        tokens = mgr.estimate_usage(messages)
        mgr.update_usage(tokens)
        assert mgr.needs_compaction() is False

    def test_warning_before_compaction(self):
        """Warning should trigger before compaction threshold."""
        mgr = ContextWindowManager(context_window=100000)
        # effective limit = 85000, warning at 60% = 51000
        mgr.update_usage(52000)
        assert mgr.should_warn() is True
        assert mgr.needs_compaction() is False

    def test_exact_threshold_triggers(self):
        """Compaction should trigger at exactly the threshold."""
        mgr = ContextWindowManager(context_window=100000)
        # effective limit = 85000, compact at 75% = 63750
        mgr.update_usage(63750)
        assert mgr.needs_compaction() is True


class TestCompactionBoundary:
    """Test safe compaction boundary finding."""

    def test_boundary_preserves_recent_messages(self):
        """Compaction should keep recent messages intact."""
        messages = _make_conversation(10)
        boundary = find_compaction_boundary(messages, keep_recent=6)
        assert boundary > 0
        kept = messages[boundary:]
        assert len(kept) >= 6

    def test_boundary_preserves_tool_pairs(self):
        """Tool call/result pairs should not be split."""
        messages = _make_conversation(10)
        boundary = find_compaction_boundary(messages, keep_recent=6)
        kept = messages[boundary:]
        assert validate_tool_pairs(kept)

    def test_boundary_always_keeps_system_prompt(self):
        """System prompt (index 0) should never be compacted."""
        messages = _make_conversation(10)
        boundary = find_compaction_boundary(messages, keep_recent=6)
        # boundary > 0 means system prompt at index 0 is in the head
        assert boundary >= 1

    def test_boundary_with_plain_conversation(self):
        """Plain conversations without tools should compact fine."""
        messages = _make_plain_conversation(15)
        boundary = find_compaction_boundary(messages, keep_recent=6)
        assert boundary > 0
        kept = messages[boundary:]
        assert len(kept) >= 6

    def test_boundary_with_many_tool_calls(self):
        """Dense tool-call conversations should find valid boundaries."""
        messages = _make_conversation(20)
        boundary = find_compaction_boundary(messages, keep_recent=6)
        assert boundary > 0
        # Verify both halves have valid tool pairs
        kept = messages[boundary:]
        assert validate_tool_pairs(kept)


class TestToolPairIntegrity:
    """Test tool pair validation across compaction scenarios."""

    def test_valid_complete_pairs(self):
        messages = _make_conversation(5)
        assert validate_tool_pairs(messages)

    def test_orphaned_tool_result_detected(self):
        """Orphaned tool_result should fail validation."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "tool", "content": "orphaned", "tool_call_id": "missing_call"},
        ]
        assert validate_tool_pairs(messages) is False

    def test_orphan_repair_scenario(self):
        """Simulate compaction creating orphans and repairing them."""
        messages = [
            {"role": "system", "content": "sys"},
            {
                "role": "tool",
                "content": "orphaned result",
                "tool_call_id": "missing_call",
            },
            {"role": "assistant", "content": "continuing..."},
            {"role": "user", "content": "ok"},
        ]
        assert validate_tool_pairs(messages) is False

        # Repair by filtering orphans
        tool_use_ids: set[str] = set()
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    if isinstance(tc, dict) and tc.get("id"):
                        tool_use_ids.add(tc["id"])

        repaired = [
            msg
            for msg in messages
            if not (
                msg.get("role") == "tool"
                and msg.get("tool_call_id") not in tool_use_ids
            )
        ]
        assert validate_tool_pairs(repaired) is True
        assert len(repaired) == 3  # system + assistant + user

    def test_multiple_tool_calls_in_one_message(self):
        """Assistant message with multiple tool calls should validate."""
        messages = [
            {"role": "system", "content": "sys"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "t1", "arguments": "{}"},
                    },
                    {
                        "id": "c2",
                        "type": "function",
                        "function": {"name": "t2", "arguments": "{}"},
                    },
                ],
            },
            {"role": "tool", "content": "r1", "tool_call_id": "c1", "name": "t1"},
            {"role": "tool", "content": "r2", "tool_call_id": "c2", "name": "t2"},
        ]
        assert validate_tool_pairs(messages) is True

    def test_partial_orphan_with_multiple_calls(self):
        """One valid and one orphaned tool result."""
        messages = [
            {"role": "system", "content": "sys"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "t1", "arguments": "{}"},
                    },
                ],
            },
            {"role": "tool", "content": "r1", "tool_call_id": "c1", "name": "t1"},
            {
                "role": "tool",
                "content": "orphaned",
                "tool_call_id": "c_missing",
                "name": "t2",
            },
        ]
        assert validate_tool_pairs(messages) is False


class TestMultipleCompactions:
    """Test multiple compaction rounds."""

    def test_multiple_compaction_tracking(self):
        """Manager should track multiple compaction rounds."""
        mgr = ContextWindowManager(context_window=50000)
        mgr.update_usage(40000)
        assert mgr.needs_compaction() is True
        mgr.mark_compacted()
        assert mgr.compaction_count == 1

        # Simulate post-compaction state
        mgr.update_usage(10000)
        assert mgr.needs_compaction() is False

        # Context grows again
        mgr.update_usage(40000)
        assert mgr.needs_compaction() is True
        mgr.mark_compacted()
        assert mgr.compaction_count == 2

    def test_warning_resets_after_compaction(self):
        """Warning flag should reset after compaction."""
        mgr = ContextWindowManager(context_window=100000)
        # Trigger warning
        mgr.update_usage(55000)
        assert mgr.should_warn() is True
        mgr.mark_warning_sent()
        assert mgr.should_warn() is False

        # Compact resets warning
        mgr.mark_compacted()
        # After compaction, if usage goes up again, should warn again
        mgr.update_usage(55000)
        assert mgr.should_warn() is True

    def test_status_reflects_compaction_count(self):
        """get_status should show compaction count."""
        mgr = ContextWindowManager(context_window=100000)
        mgr.mark_compacted()
        mgr.mark_compacted()
        status = mgr.get_status()
        assert status["compaction_count"] == 2


class TestTokenEstimation:
    """Test token estimation accuracy for different message types."""

    def test_tool_calls_add_tokens(self):
        """Messages with tool calls should estimate more tokens."""
        plain = [{"role": "assistant", "content": "Hello world"}]
        with_tools = [
            {
                "role": "assistant",
                "content": "Hello world",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "search",
                            "arguments": '{"query": "test data"}',
                        },
                    }
                ],
            }
        ]
        plain_tokens = estimate_tokens_for_messages(plain)
        tool_tokens = estimate_tokens_for_messages(with_tools)
        assert tool_tokens > plain_tokens

    def test_empty_conversation(self):
        """Empty message list should return 0."""
        assert estimate_tokens_for_messages([]) == 0

    def test_estimation_scales_with_content(self):
        """Longer content should produce more tokens."""
        short = [{"role": "user", "content": "Hi"}]
        long = [{"role": "user", "content": "x" * 10000}]
        assert estimate_tokens_for_messages(long) > estimate_tokens_for_messages(short)
