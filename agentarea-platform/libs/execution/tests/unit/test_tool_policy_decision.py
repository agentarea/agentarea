"""Unit tests for the unified tool-call policy decision (decide_tool_action).

Default-allow: a tool the agent is composed with runs unless policy restricts it.
The decision function only ever sees a tool the agent already offers (that is why
it is being asked about), so composition is the allow — policy carries the
subtractions: DENY, REQUIRE_APPROVAL, and (opt-in) an explicit allowlist. This
replaces the old deny-by-default, where every built-in tool needed a hand-typed
allow row just to run.
"""

from agentarea_execution.workflows.helpers import ToolAction, decide_tool_action


def test_no_policy_allows():
    # A composed tool with no governing policy is allowed — deny-by-default is gone.
    assert decide_tool_action(None, "shell") is ToolAction.ALLOW
    assert decide_tool_action({}, "shell") is ToolAction.ALLOW


def test_absent_allowlist_allows():
    assert decide_tool_action({"tools": {"denied": []}}, "shell") is ToolAction.ALLOW
    assert decide_tool_action({"tools": {"allowed": None}}, "shell") is ToolAction.ALLOW


def test_empty_allowlist_allows():
    # An empty allowlist is "no allowlist in use", not "deny everything" —
    # restriction is expressed by composing fewer tools or by DENY rules.
    assert decide_tool_action({"tools": {"allowed": []}}, "anything") is ToolAction.ALLOW


def test_denied_tool_is_denied_others_allowed():
    policy = {"tools": {"denied": ["shell"]}}
    assert decide_tool_action(policy, "shell") is ToolAction.DENY
    assert decide_tool_action(policy, "web_search") is ToolAction.ALLOW


def test_denied_supports_globs():
    policy = {"tools": {"denied": ["web_*"]}}
    assert decide_tool_action(policy, "web_search") is ToolAction.DENY
    assert decide_tool_action(policy, "shell") is ToolAction.ALLOW


def test_explicit_allowlist_still_restricts_when_present():
    # A non-empty allowlist is an opt-in restriction a governor may set: only the
    # listed tools run. Absence means allow; presence means "only these".
    policy = {"tools": {"allowed": ["web_search"]}}
    assert decide_tool_action(policy, "web_search") is ToolAction.ALLOW
    assert decide_tool_action(policy, "shell") is ToolAction.DENY


def test_explicit_allowlist_supports_globs():
    policy = {"tools": {"allowed": ["web_*"]}}
    assert decide_tool_action(policy, "web_search") is ToolAction.ALLOW
    assert decide_tool_action(policy, "shell") is ToolAction.DENY


def test_global_approval_requires_approval():
    policy = {"approval": {"requires_human_approval": True}}
    assert decide_tool_action(policy, "web_search") is ToolAction.REQUIRE_APPROVAL


def test_escalation_rule_requires_approval_for_that_tool_only():
    policy = {"approval": {"escalation_rules": ["shell"]}}
    assert decide_tool_action(policy, "shell") is ToolAction.REQUIRE_APPROVAL
    assert decide_tool_action(policy, "web_search") is ToolAction.ALLOW


def test_deny_takes_precedence_over_approval():
    policy = {
        "tools": {"denied": ["shell"]},
        "approval": {"requires_human_approval": True},
    }
    assert decide_tool_action(policy, "shell") is ToolAction.DENY


def test_deny_takes_precedence_over_allowlist():
    policy = {"tools": {"allowed": ["shell"], "denied": ["shell"]}}
    assert decide_tool_action(policy, "shell") is ToolAction.DENY


def test_a_tool_outside_an_explicit_allowlist_is_not_escalated_it_is_denied():
    # Restriction wins over escalation: a tool the allowlist excludes never runs,
    # so it is never offered for approval.
    policy = {
        "tools": {"allowed": ["web_search"]},
        "approval": {"escalation_rules": ["shell"]},
    }
    assert decide_tool_action(policy, "shell") is ToolAction.DENY
