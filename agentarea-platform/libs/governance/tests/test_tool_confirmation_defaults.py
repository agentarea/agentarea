"""A tool's own confirmation declaration is a policy input, not a second gate.

ShellToolset declares ``requires_user_confirmation=True``. Nothing read it: the
flag travelled from the decorator through the loader into the agent config and
died there, so bash ran in the sandbox without ever asking. Meanwhile the PDP
decided approval purely from the policy snapshot.

Two sources of "requires confirmation" that never met is one too many. The
declaration now enters the single place that decides — the resolved policy —
as a default, and ``auto_approved`` is how a policy overrides it. The tool knows
bash is dangerous; the policy knows whether this workspace trusts it; one layer
resolves both.
"""

import pytest
from agentarea_governance.domain.policies import (
    ApprovalPolicy,
    PolicyDocument,
    PolicyResolver,
    PolicyValidationError,
    ToolsPolicy,
)


def _escalations(effective) -> list[str]:
    return list(effective.approval.escalation_rules) if effective.approval else []


def test_a_declared_tool_requires_approval_when_the_policy_is_silent():
    effective = PolicyResolver().resolve([], tool_confirmation_defaults=["shell_bash"])

    assert "shell_bash" in _escalations(effective)


def test_an_undeclared_tool_is_not_escalated():
    effective = PolicyResolver().resolve([], tool_confirmation_defaults=["shell_bash"])

    assert "web_search" not in _escalations(effective)


def test_no_declarations_leave_the_snapshot_untouched():
    effective = PolicyResolver().resolve([])

    assert _escalations(effective) == []


def test_a_policy_can_auto_approve_a_declared_tool():
    policy = PolicyDocument(approval=ApprovalPolicy(auto_approved=["shell_bash"]))

    effective = PolicyResolver().resolve([policy], tool_confirmation_defaults=["shell_bash"])

    assert "shell_bash" not in _escalations(effective)


def test_auto_approval_does_not_silence_an_explicit_escalation():
    # auto_approved cancels the tool's own default, never a human's decision to
    # escalate. Otherwise the escape hatch would override the policy it serves.
    policy = PolicyDocument(
        approval=ApprovalPolicy(escalation_rules=["shell_bash"], auto_approved=["shell_bash"])
    )

    effective = PolicyResolver().resolve([policy], tool_confirmation_defaults=["shell_bash"])

    assert "shell_bash" in _escalations(effective)


def test_a_lower_scope_cannot_auto_approve_what_a_higher_scope_did_not():
    workspace = PolicyDocument(approval=ApprovalPolicy(auto_approved=[]))
    task = PolicyDocument(approval=ApprovalPolicy(auto_approved=["shell_bash"]))

    with pytest.raises(PolicyValidationError):
        PolicyResolver().resolve([workspace, task])


def test_a_lower_scope_may_narrow_an_inherited_auto_approval():
    workspace = PolicyDocument(approval=ApprovalPolicy(auto_approved=["shell_bash", "web_fetch"]))
    task = PolicyDocument(approval=ApprovalPolicy(auto_approved=["shell_bash"]))

    effective = PolicyResolver().resolve(
        [workspace, task], tool_confirmation_defaults=["shell_bash", "web_fetch"]
    )

    assert "shell_bash" not in _escalations(effective)
    assert "web_fetch" in _escalations(effective)


def test_declared_tools_survive_the_json_round_trip_the_workflow_reads():
    # The workflow gate reads the snapshot as a plain dict over Temporal, not as
    # a model — a declaration that does not survive to_json_dict never gates.
    effective = PolicyResolver().resolve([], tool_confirmation_defaults=["shell_bash"])

    assert "shell_bash" in effective.to_json_dict()["approval"]["escalation_rules"]


def test_the_declaration_reaches_the_pdp_verdict():
    # The point of all of the above: what the tool declares must change what the
    # gate decides. Anything less leaves the flag decorative.
    from agentarea_common.auth.tool_authorization import (
        ToolAuthorizationAction,
        decide_tool_policy,
    )

    allow_everything = PolicyDocument(tools=ToolsPolicy(allowed=["*"]))
    effective = PolicyResolver().resolve(
        [allow_everything], tool_confirmation_defaults=["shell_bash"]
    )
    snapshot = effective.to_json_dict()

    assert decide_tool_policy(snapshot, "shell_bash").action is (
        ToolAuthorizationAction.REQUIRE_APPROVAL
    )
    assert decide_tool_policy(snapshot, "web_search").action is ToolAuthorizationAction.ALLOW


def test_an_auto_approved_declaration_reaches_the_pdp_as_allow():
    from agentarea_common.auth.tool_authorization import (
        ToolAuthorizationAction,
        decide_tool_policy,
    )

    policy = PolicyDocument(
        tools=ToolsPolicy(allowed=["*"]),
        approval=ApprovalPolicy(auto_approved=["shell_bash"]),
    )
    effective = PolicyResolver().resolve([policy], tool_confirmation_defaults=["shell_bash"])

    decision = decide_tool_policy(effective.to_json_dict(), "shell_bash")

    assert decision.action is ToolAuthorizationAction.ALLOW
