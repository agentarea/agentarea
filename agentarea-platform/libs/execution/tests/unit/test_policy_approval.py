"""Human approval is policy-driven: ApprovalPolicy is the single source of truth
for whether a tool call needs a human, replacing the old per-tool config.
"""

from agentarea_execution.workflows.helpers import (
    caller_can_approve,
    policy_approvers,
    policy_requires_approval,
)


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


def test_policy_approvers_extracts_subject_refs():
    assert policy_approvers({"approval": {"approvers": ["user:alice"]}}) == ["user:alice"]
    assert policy_approvers(None) == []
    assert policy_approvers({"approval": {}}) == []


def test_empty_approvers_allows_any_caller():
    assert caller_can_approve([], "alice") is True


def test_listed_user_can_approve():
    assert caller_can_approve(["user:alice", "user:bob"], "alice") is True


def test_unlisted_user_cannot_approve():
    assert caller_can_approve(["user:alice"], "carol") is False


def test_userset_subject_does_not_grant_approval_yet():
    assert caller_can_approve(["group:security#member"], "alice") is False
    assert caller_can_approve(["group:x", "user:alice"], "alice") is True
