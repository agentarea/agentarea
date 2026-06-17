"""Tests for execute_mcp_tool_activity's local policy gate."""

from agentarea_execution.activities.agent_execution_activities import _tool_policy_denial_reason


def test_activity_tool_gate_denies_when_policy_missing():
    assert _tool_policy_denial_reason(None, "web_search")
    assert _tool_policy_denial_reason({}, "web_search")


def test_activity_tool_gate_allows_explicit_allowlist_match():
    assert _tool_policy_denial_reason({"tools": {"allowed": ["web_*"]}}, "web_search") is None


def test_activity_tool_gate_denies_disallowed_tool():
    reason = _tool_policy_denial_reason({"tools": {"allowed": ["web_*"]}}, "shell_exec")
    assert reason
    assert "not explicitly allowed" in reason


def test_activity_tool_gate_denies_approval_only_direct_execution():
    reason = _tool_policy_denial_reason(
        {
            "tools": {"allowed": ["shell_exec"]},
            "approval": {"escalation_rules": ["shell_exec"]},
        },
        "shell_exec",
    )
    assert reason
    assert "requires approval" in reason
