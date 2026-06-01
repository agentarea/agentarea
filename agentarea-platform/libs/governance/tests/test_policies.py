"""Tests for typed governance policy resolution."""

import pytest
from agentarea_governance.domain.policies import (
    ApprovalPolicy,
    BudgetPolicy,
    ContentSafetyPolicy,
    PolicyDocument,
    PolicyResolver,
    PolicyValidationError,
    PolicyValidator,
    TokenPolicy,
    ToolsPolicy,
)


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
                PolicyDocument(
                    approval=ApprovalPolicy(requires_human_approval=True)
                ),
                PolicyDocument(
                    approval=ApprovalPolicy(requires_human_approval=False)
                ),
            ]
        )


def test_content_safety_can_only_get_stricter():
    with pytest.raises(PolicyValidationError):
        PolicyResolver().resolve(
            [
                PolicyDocument(
                    content_safety=ContentSafetyPolicy(
                        prompt_injection_detection_enabled=True
                    )
                ),
                PolicyDocument(
                    content_safety=ContentSafetyPolicy(
                        prompt_injection_detection_enabled=False
                    )
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
        [
            PolicyDocument(
                budget=BudgetPolicy(run_budget_usd="10.00", service_budget_usd="5.00")
            )
        ]
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
                    semantic_guard_threshold=70,
                )
            )
        ]
    )

    state = effective.to_execution_state()

    content_safety = state["content_safety"]
    assert content_safety["prompt_injection_enabled"] is False
    assert content_safety["output_sanitizer_enabled"] is True
    assert content_safety["semantic_guard_threshold"] == 70


def test_to_execution_state_empty_policy_is_empty_state():
    assert PolicyResolver().resolve([]).to_execution_state() == {}


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
