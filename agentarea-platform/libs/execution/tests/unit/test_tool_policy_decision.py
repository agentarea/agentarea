"""Unit tests for the unified tool-call policy decision (decide_tool_action)."""

from agentarea_execution.workflows.helpers import ToolAction, decide_tool_action


def test_no_policy_denies():
    assert decide_tool_action(None, "shell") is ToolAction.DENY
    assert decide_tool_action({}, "shell") is ToolAction.DENY


def test_denied_tool_is_denied():
    policy = {"tools": {"denied": ["shell"]}}
    assert decide_tool_action(policy, "shell") is ToolAction.DENY
    assert decide_tool_action(policy, "web_search") is ToolAction.DENY


def test_allowlist_mode_denies_unlisted():
    policy = {"tools": {"allowed": ["web_search"]}}
    assert decide_tool_action(policy, "web_search") is ToolAction.ALLOW
    assert decide_tool_action(policy, "shell") is ToolAction.DENY


def test_empty_allowlist_denies_everything():
    policy = {"tools": {"allowed": []}}
    assert decide_tool_action(policy, "anything") is ToolAction.DENY


def test_allowed_none_denies_by_default():
    policy = {"tools": {"allowed": None, "denied": []}}
    assert decide_tool_action(policy, "anything") is ToolAction.DENY


def test_allowlist_supports_globs():
    policy = {"tools": {"allowed": ["web_*"]}}
    assert decide_tool_action(policy, "web_search") is ToolAction.ALLOW
    assert decide_tool_action(policy, "shell") is ToolAction.DENY


def test_global_approval_requires_approval():
    policy = {"tools": {"allowed": ["web_search"]}, "approval": {"requires_human_approval": True}}
    assert decide_tool_action(policy, "web_search") is ToolAction.REQUIRE_APPROVAL


def test_escalation_rule_requires_approval_for_that_tool_only():
    policy = {"tools": {"allowed": ["shell", "web_search"]}, "approval": {"escalation_rules": ["shell"]}}
    assert decide_tool_action(policy, "shell") is ToolAction.REQUIRE_APPROVAL
    assert decide_tool_action(policy, "web_search") is ToolAction.ALLOW


def test_deny_takes_precedence_over_approval():
    # A denied tool is rejected outright, never escalated for approval.
    policy = {
        "tools": {"denied": ["shell"]},
        "approval": {"requires_human_approval": True},
    }
    assert decide_tool_action(policy, "shell") is ToolAction.DENY


def test_deny_takes_precedence_over_allowlist():
    policy = {"tools": {"allowed": ["shell"], "denied": ["shell"]}}
    assert decide_tool_action(policy, "shell") is ToolAction.DENY


def test_allowed_tool_still_escalates_when_in_rules():
    policy = {
        "tools": {"allowed": ["shell"]},
        "approval": {"escalation_rules": ["shell"]},
    }
    assert decide_tool_action(policy, "shell") is ToolAction.REQUIRE_APPROVAL
