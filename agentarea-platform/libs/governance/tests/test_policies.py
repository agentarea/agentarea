"""Tests for typed governance policy resolution."""

import pytest
from agentarea_governance.domain.policies import (
    ApprovalPolicy,
    BudgetPolicy,
    ContentSafetyPolicy,
    ExecutionLimitsPolicy,
    PolicyDocument,
    PolicyResolver,
    PolicyValidationError,
    PolicyValidator,
    RuntimePolicyContractError,
    TokenPolicy,
    ToolsPolicy,
    effective_policy_from_json,
    is_approver,
)
from pydantic import ValidationError


def test_execution_limits_tighten_by_minimum():
    effective = PolicyResolver().resolve(
        [
            PolicyDocument(
                execution=ExecutionLimitsPolicy(
                    max_model_turns=100,
                    max_tool_calls_per_turn=10,
                    max_tool_calls_total=1000,
                )
            ),
            PolicyDocument(
                execution=ExecutionLimitsPolicy(
                    max_model_turns=24,
                    max_tool_calls_per_turn=5,
                    max_tool_calls_total=100,
                )
            ),
        ]
    )

    assert effective.execution == ExecutionLimitsPolicy(
        max_model_turns=24,
        max_tool_calls_per_turn=5,
        max_tool_calls_total=100,
    )


def test_execution_limits_cannot_be_loosened():
    with pytest.raises(PolicyValidationError, match="max_model_turns"):
        PolicyResolver().resolve(
            [
                PolicyDocument(execution=ExecutionLimitsPolicy(max_model_turns=100)),
                PolicyDocument(execution=ExecutionLimitsPolicy(max_model_turns=101)),
            ]
        )


def test_runtime_contract_requires_explicit_persisted_limits():
    effective = PolicyResolver().resolve([])

    with pytest.raises(RuntimePolicyContractError) as exc_info:
        effective.require_runtime_contract()

    assert exc_info.value.missing_fields == (
        "budget.run_budget_usd",
        "tokens.max_tokens",
        "tokens.max_tokens_per_call",
        "execution.max_model_turns",
        "execution.max_tool_calls_per_turn",
        "execution.max_tool_calls_total",
    )


def test_runtime_contract_accepts_complete_policy():
    effective = PolicyResolver().resolve(
        [
            PolicyDocument(
                budget=BudgetPolicy(run_budget_usd="50.00"),
                tokens=TokenPolicy(max_tokens=20_000_000, max_tokens_per_call=100_000),
                execution=ExecutionLimitsPolicy(
                    max_model_turns=100,
                    max_tool_calls_per_turn=10,
                    max_tool_calls_total=1000,
                ),
            )
        ]
    )

    assert effective.require_runtime_contract() is effective
    runtime = effective.runtime_contract()
    assert str(runtime.run_budget_usd) == "50.00"
    assert runtime.max_tokens == 20_000_000
    assert runtime.max_tokens_per_call == 100_000
    assert runtime.max_model_turns == 100
    assert runtime.max_tool_calls_per_turn == 10
    assert runtime.max_tool_calls_total == 1000


@pytest.mark.parametrize(
    ("policy_type", "kwargs"),
    [
        (BudgetPolicy, {"run_budget_usd": "0"}),
        (BudgetPolicy, {"service_budget_usd": "-1"}),
        (TokenPolicy, {"max_tokens": 0}),
        (TokenPolicy, {"max_tokens_per_call": -1}),
    ],
)
def test_runtime_budget_and_token_limits_must_be_positive(policy_type, kwargs):
    with pytest.raises(ValidationError, match="greater than"):
        policy_type(**kwargs)


def test_numeric_ceilings_tighten_by_minimum():
    effective = PolicyResolver().resolve(
        [
            PolicyDocument(budget=BudgetPolicy(monthly_spend_cap_usd="100.00")),
            PolicyDocument(budget=BudgetPolicy(monthly_spend_cap_usd="75.00")),
            PolicyDocument(budget=BudgetPolicy(monthly_spend_cap_usd="50.00")),
        ]
    )

    assert str(effective.budget.monthly_spend_cap_usd) == "50.00"


def test_numeric_loosening_is_rejected():
    with pytest.raises(PolicyValidationError):
        PolicyResolver().resolve(
            [
                PolicyDocument(budget=BudgetPolicy(monthly_spend_cap_usd="100.00")),
                PolicyDocument(budget=BudgetPolicy(monthly_spend_cap_usd="200.00")),
            ]
        )


def test_tool_denylist_unions_and_allowlist_tightens():
    effective = PolicyResolver().resolve(
        [
            PolicyDocument(
                tools=ToolsPolicy(
                    allowed=["github_*", "slack_*"],
                    denied=["payment_*"],
                )
            ),
            PolicyDocument(
                tools=ToolsPolicy(
                    allowed=["github_*"],
                    denied=["delete_*"],
                )
            ),
            PolicyDocument(
                tools=ToolsPolicy(
                    allowed=["github_create_issue"],
                    denied=["admin_*"],
                )
            ),
        ]
    )

    assert effective.tools.allowed == ["github_create_issue"]
    assert effective.tools.denied == ["payment_*", "delete_*", "admin_*"]


def test_tool_allowlist_widening_is_rejected():
    with pytest.raises(PolicyValidationError):
        PolicyResolver().resolve(
            [
                PolicyDocument(tools=ToolsPolicy(allowed=["github_*"])),
                PolicyDocument(tools=ToolsPolicy(allowed=["*"])),
            ]
        )


def test_child_delegated_task_cannot_widen_parent_tool_policy():
    parent_effective_policy = PolicyDocument(tools=ToolsPolicy(allowed=["github_*"]))
    child_task_policy = PolicyDocument(tools=ToolsPolicy(allowed=["*"]))

    with pytest.raises(PolicyValidationError, match=r"tools\.allowed"):
        PolicyValidator().validate_chain(
            [parent_effective_policy, child_task_policy],
            source_policy_ids=["parent-effective", "child-task"],
        )


def test_tool_allowlist_accepts_more_specific_wildcard_prefix():
    effective = PolicyResolver().resolve(
        [
            PolicyDocument(tools=ToolsPolicy(allowed=["github_*"])),
            PolicyDocument(tools=ToolsPolicy(allowed=["github_issue_*"])),
        ]
    )

    assert effective.tools.allowed == ["github_issue_*"]


def test_approval_cannot_be_disabled_and_rules_union():
    effective = PolicyResolver().resolve(
        [
            PolicyDocument(
                approval=ApprovalPolicy(
                    requires_human_approval=True,
                    escalation_rules=["payment_*"],
                )
            ),
            PolicyDocument(approval=ApprovalPolicy(escalation_rules=["delete_*"])),
        ]
    )

    assert effective.approval.requires_human_approval is True
    assert effective.approval.escalation_rules == ["payment_*", "delete_*"]

    with pytest.raises(PolicyValidationError):
        PolicyResolver().resolve(
            [
                PolicyDocument(approval=ApprovalPolicy(requires_human_approval=True)),
                PolicyDocument(approval=ApprovalPolicy(requires_human_approval=False)),
            ]
        )


def test_per_tool_approvers_union_across_scopes():
    # A workspace and an agent scope both require approval for the same tool but
    # name different approvers; the merge keeps both, keyed by the tool.
    effective = PolicyResolver().resolve(
        [
            PolicyDocument(
                approval=ApprovalPolicy(
                    escalation_rules=["launch_task"],
                    approvers_by_tool={"launch_task": ["user:alice"]},
                )
            ),
            PolicyDocument(
                approval=ApprovalPolicy(
                    escalation_rules=["launch_task", "delete_file"],
                    approvers_by_tool={
                        "launch_task": ["user:bob"],
                        "delete_file": ["user:carol"],
                    },
                )
            ),
        ]
    )

    assert effective.approval.approvers_by_tool == {
        "launch_task": ["user:alice", "user:bob"],
        "delete_file": ["user:carol"],
    }


def test_content_safety_can_only_get_stricter():
    with pytest.raises(PolicyValidationError):
        PolicyResolver().resolve(
            [
                PolicyDocument(
                    content_safety=ContentSafetyPolicy(prompt_injection_detection_enabled=True)
                ),
                PolicyDocument(
                    content_safety=ContentSafetyPolicy(prompt_injection_detection_enabled=False)
                ),
            ]
        )


def test_effective_policy_serializes_money_as_json_string():
    effective = PolicyResolver().resolve(
        [PolicyDocument(budget=BudgetPolicy(run_budget_usd="1.25"))]
    )

    assert effective.to_json_dict()["budget"]["run_budget_usd"] == "1.25"


def test_to_execution_state_emits_floats_for_money():
    effective = PolicyResolver().resolve(
        [PolicyDocument(budget=BudgetPolicy(run_budget_usd="10.00", service_budget_usd="5.00"))]
    )

    state = effective.to_execution_state()

    assert state["budget_usd"] == 10.0
    assert isinstance(state["budget_usd"], float)
    assert state["service_budget_usd"] == 5.0
    assert isinstance(state["service_budget_usd"], float)


def test_to_execution_state_merges_runtime_counters_as_floats():
    effective = PolicyResolver().resolve(
        [PolicyDocument(budget=BudgetPolicy(run_budget_usd="10.00"))]
    )

    state = effective.to_execution_state(
        {"cost_used": "3.50", "service_cost_used": "1.00", "tokens_used": 1200}
    )

    assert state["cost_used"] == 3.5
    assert isinstance(state["cost_used"], float)
    assert state["service_cost_used"] == 1.0
    assert isinstance(state["service_cost_used"], float)
    assert state["tokens_used"] == 1200


def test_to_execution_state_maps_tools_tokens_and_escalation():
    effective = PolicyResolver().resolve(
        [
            PolicyDocument(
                tokens=TokenPolicy(max_tokens=50000),
                tools=ToolsPolicy(allowed=["web_*"], denied=["payment_*"]),
                approval=ApprovalPolicy(escalation_rules=["delete_*"]),
            )
        ]
    )

    state = effective.to_execution_state()

    assert state["max_tokens"] == 50000
    assert state["tools_config"] == {"allowed": ["web_*"], "denied": ["payment_*"]}
    assert state["escalation_rules"] == ["delete_*"]


def test_to_execution_state_emits_content_safety_flags():
    effective = PolicyResolver().resolve(
        [
            PolicyDocument(
                content_safety=ContentSafetyPolicy(
                    prompt_injection_detection_enabled=False,
                    output_sanitizer_enabled=True,
                )
            )
        ]
    )

    state = effective.to_execution_state()

    content_safety = state["content_safety"]
    assert content_safety["prompt_injection_enabled"] is False
    assert content_safety["output_sanitizer_enabled"] is True


def test_to_execution_state_empty_policy_is_empty_state():
    assert PolicyResolver().resolve([]).to_execution_state() == {}


def test_approvers_merge_union_across_scopes():
    effective = PolicyResolver().resolve(
        [
            PolicyDocument(approval=ApprovalPolicy(approvers=["user:alice"])),
            PolicyDocument(approval=ApprovalPolicy(approvers=["user:bob", "user:alice"])),
        ]
    )
    assert effective.approval.approvers == ["user:alice", "user:bob"]


def test_approvers_must_be_typed_subject_refs_not_raw_ids():
    with pytest.raises(ValueError, match="subject ref"):
        ApprovalPolicy(approvers=["alice"])  # raw id without type is rejected


def test_approvers_accept_usersets_and_groups():
    policy = ApprovalPolicy(approvers=["user:alice", "group:security#member", "role:admin"])
    assert policy.approvers == ["user:alice", "group:security#member", "role:admin"]


def test_is_approver_matches_direct_user_only():
    assert is_approver("alice", ["user:alice", "user:bob"]) is True
    assert is_approver("carol", ["user:alice", "user:bob"]) is False


def test_is_approver_does_not_resolve_usersets_yet():
    # group/userset subjects are stored but unresolved until a membership model (#198)
    assert is_approver("alice", ["group:security#member"]) is False
    # a direct user ref still matches even alongside an unresolved userset
    assert is_approver("alice", ["group:security#member", "user:alice"]) is True


def test_snapshot_roundtrips_losslessly_for_immutability():
    """The snapshot frozen at task creation must reach the runtime unchanged.

    Guards against a future change re-resolving policy at runtime: whatever was
    stored at creation must produce an identical execution_state when reloaded,
    so a policy edit after the task starts cannot alter the running task.
    """
    effective = PolicyResolver().resolve(
        [
            PolicyDocument(
                budget=BudgetPolicy(run_budget_usd="10.00"),
                tools=ToolsPolicy(allowed=["web_*"], denied=["payment_*"]),
                approval=ApprovalPolicy(escalation_rules=["delete_*"]),
            )
        ],
        source_policy_ids=["workspace-policy", "agent-policy"],
    )

    snapshot = effective.to_json_dict()
    restored = effective_policy_from_json(snapshot)

    assert restored.to_json_dict() == snapshot
    assert restored.to_execution_state() == effective.to_execution_state()


def test_policy_validator_exposes_chain_validation_contract():
    effective = PolicyValidator().validate_chain(
        [
            PolicyDocument(budget=BudgetPolicy(monthly_spend_cap_usd="100.00")),
            PolicyDocument(budget=BudgetPolicy(monthly_spend_cap_usd="50.00")),
        ],
        source_policy_ids=["workspace-policy", "agent-policy"],
    )

    assert str(effective.budget.monthly_spend_cap_usd) == "50.00"
    assert effective.source_policy_ids == ["workspace-policy", "agent-policy"]
