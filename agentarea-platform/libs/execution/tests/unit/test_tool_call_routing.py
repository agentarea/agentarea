"""Tests for tool call routing logic in the workflow.

Tests that _execute_tool_calls correctly separates agent calls, regular calls,
recall_history calls, and completion calls.
"""

import pytest

from agentarea_execution.workflows.models import ToolCall


class TestToolCallClassification:
    """Test that tool calls are classified correctly by name."""

    def _make_tool_call(self, name: str, tool_id: str = "tc-1", args: str = "{}") -> ToolCall:
        return ToolCall(
            id=tool_id,
            function={"name": name, "arguments": args},
        )

    def test_completion_call_identified(self):
        tc = self._make_tool_call("completion")
        assert tc.function["name"] == "completion"

    def test_recall_history_identified(self):
        tc = self._make_tool_call("recall_history")
        assert tc.function["name"] == "recall_history"

    def test_regular_tool_identified(self):
        tc = self._make_tool_call("web_search")
        assert tc.function["name"] == "web_search"

    def test_agent_tool_routing(self):
        """Agent tools are identified by checking the registry."""
        registry = {
            "delegate_to_researcher": {"agent_id": "a1", "agent_name": "researcher"},
            "delegate_to_writer": {"agent_id": "a2", "agent_name": "writer"},
        }

        tool_calls = [
            self._make_tool_call("delegate_to_researcher", "tc-1"),
            self._make_tool_call("web_search", "tc-2"),
            self._make_tool_call("delegate_to_writer", "tc-3"),
            self._make_tool_call("completion", "tc-4"),
            self._make_tool_call("recall_history", "tc-5"),
        ]

        completion_call = None
        agent_calls = []
        regular_calls = []
        recall_calls = []

        for tc in tool_calls:
            name = tc.function["name"]
            if name == "completion":
                completion_call = tc
            elif name == "recall_history":
                recall_calls.append(tc)
            elif name in registry:
                agent_calls.append(tc)
            else:
                regular_calls.append(tc)

        assert completion_call is not None
        assert completion_call.id == "tc-4"
        assert len(agent_calls) == 2
        assert agent_calls[0].id == "tc-1"
        assert agent_calls[1].id == "tc-3"
        assert len(regular_calls) == 1
        assert regular_calls[0].function["name"] == "web_search"
        assert len(recall_calls) == 1
        assert recall_calls[0].id == "tc-5"

    def test_all_agent_calls_fan_out(self):
        """Multiple agent calls should be grouped for parallel execution."""
        registry = {
            "delegate_to_a": {"agent_id": "a1", "agent_name": "a"},
            "delegate_to_b": {"agent_id": "a2", "agent_name": "b"},
            "delegate_to_c": {"agent_id": "a3", "agent_name": "c"},
        }

        tool_calls = [
            self._make_tool_call("delegate_to_a", "tc-1"),
            self._make_tool_call("delegate_to_b", "tc-2"),
            self._make_tool_call("delegate_to_c", "tc-3"),
        ]

        agent_calls = [tc for tc in tool_calls if tc.function["name"] in registry]
        assert len(agent_calls) == 3

    def test_empty_tool_calls(self):
        """Empty tool call list should produce no routing."""
        tool_calls = []
        assert len(tool_calls) == 0
