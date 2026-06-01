"""Human approval is policy-driven: ApprovalPolicy is the single source of truth
for whether a tool call needs a human, replacing the old per-tool config.
"""

from agentarea_execution.workflows.helpers import policy_requires_approval


def test_no_policy_no_approval():
    assert policy_requires_approval(None, "send_email") is False
    assert policy_requires_approval({}, "send_email") is False


def test_requires_human_approval_global_applies_to_any_tool():
    policy = {"approval": {"requires_human_approval": True}}
    assert policy_requires_approval(policy, "anything") is True


def test_tool_in_escalation_rules_requires_approval():
    policy = {"approval": {"escalation_rules": ["send_email", "delete_file"]}}
    assert policy_requires_approval(policy, "send_email") is True
    assert policy_requires_approval(policy, "delete_file") is True


def test_tool_not_in_escalation_rules_no_approval():
    policy = {"approval": {"escalation_rules": ["send_email"]}}
    assert policy_requires_approval(policy, "read_db") is False


def test_empty_approval_section_no_approval():
    assert policy_requires_approval({"approval": {}}, "send_email") is False
    assert policy_requires_approval({"tools": {"allowed": ["x"]}}, "send_email") is False
