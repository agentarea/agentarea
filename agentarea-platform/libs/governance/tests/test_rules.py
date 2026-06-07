"""Tests for the unified policy rule model, parse_target, and the compiler."""

from decimal import Decimal

import pytest
from agentarea_governance.domain.policies import PolicyDocument
from agentarea_governance.domain.rules import (
    PolicyEffect,
    PolicyRule,
    PolicySubjectType,
    parse_target,
    rules_to_document,
)


def _rule(target: str, effect: PolicyEffect, **params) -> PolicyRule:
    return PolicyRule(
        subject_type=PolicySubjectType.WORKSPACE,
        subject_id="ws-a",
        target=target,
        effect=effect,
        params=params,
    )


class TestParseTarget:
    def test_tool_with_id(self):
        assert parse_target("tool:send_email") == ("tool", "send_email")

    def test_tool_wildcard(self):
        assert parse_target("tool:*") == ("tool", "*")

    def test_bare_kind_yields_none_value(self):
        assert parse_target("spend") == ("spend", None)

    def test_star_is_all(self):
        assert parse_target("*") == ("all", None)

    def test_service_and_tokens_and_content(self):
        assert parse_target("service") == ("service", None)
        assert parse_target("tokens") == ("tokens", None)
        assert parse_target("content") == ("content", None)

    @pytest.mark.parametrize("bad", ["", "garbage", "bogus:thing", ":x", "tool:"])
    def test_rejects_garbage(self, bad):
        with pytest.raises(ValueError):
            parse_target(bad)


class TestCompiler:
    def test_monthly_spend_cap(self):
        doc = rules_to_document(
            [_rule("spend", PolicyEffect.CAP, amount_usd="10.00", period="month")]
        )
        assert doc.budget is not None
        assert Decimal(str(doc.budget.monthly_spend_cap_usd)) == Decimal("10.00")

    def test_run_spend_cap(self):
        doc = rules_to_document(
            [_rule("spend", PolicyEffect.CAP, amount_usd="2.50", period="run")]
        )
        assert Decimal(str(doc.budget.run_budget_usd)) == Decimal("2.50")

    def test_service_cap(self):
        doc = rules_to_document([_rule("service", PolicyEffect.CAP, amount_usd="3.00")])
        assert Decimal(str(doc.budget.service_budget_usd)) == Decimal("3.00")

    def test_token_caps(self):
        doc = rules_to_document(
            [_rule("tokens", PolicyEffect.CAP, max_tokens=1000, max_tokens_per_call=100)]
        )
        assert doc.tokens.max_tokens == 1000
        assert doc.tokens.max_tokens_per_call == 100

    def test_deny_tool(self):
        doc = rules_to_document([_rule("tool:rm_rf", PolicyEffect.DENY)])
        assert doc.tools.denied == ["rm_rf"]

    def test_allow_tool(self):
        doc = rules_to_document([_rule("tool:search", PolicyEffect.ALLOW)])
        assert doc.tools.allowed == ["search"]

    def test_deny_wildcard_tool_is_skipped(self):
        doc = rules_to_document([_rule("tool:*", PolicyEffect.DENY)])
        assert doc.tools is None

    def test_approval_on_tool_goes_to_escalation_rules(self):
        """The safety invariant: approval-on-tool must land in escalation_rules
        so helpers.policy_requires_approval keeps pausing on that tool."""
        doc = rules_to_document([_rule("tool:send_email", PolicyEffect.APPROVAL)])
        assert doc.approval is not None
        assert "send_email" in doc.approval.escalation_rules
        assert doc.approval.requires_human_approval is None

    def test_global_approval_sets_requires_human_approval(self):
        doc = rules_to_document([_rule("*", PolicyEffect.APPROVAL)])
        assert doc.approval.requires_human_approval is True

    def test_approval_wildcard_tool_sets_global(self):
        doc = rules_to_document([_rule("tool:*", PolicyEffect.APPROVAL)])
        assert doc.approval.requires_human_approval is True

    def test_approval_approvers_merged(self):
        doc = rules_to_document(
            [_rule("tool:send_email", PolicyEffect.APPROVAL, approvers=["user:alice"])]
        )
        assert doc.approval.approvers == ["user:alice"]

    def test_content_safety(self):
        doc = rules_to_document(
            [_rule("content", PolicyEffect.SAFETY, prompt_injection=True, output_sanitizer=False)]
        )
        assert doc.content_safety.prompt_injection_detection_enabled is True
        assert doc.content_safety.output_sanitizer_enabled is False

    def test_disabled_rule_ignored(self):
        rule = _rule("tool:x", PolicyEffect.DENY)
        rule.enabled = False
        assert rules_to_document([rule]).tools is None

    def test_unknown_rule_skipped_not_crash(self):
        rule = _rule("model:gpt-4", PolicyEffect.DENY)
        doc = rules_to_document([rule])
        assert isinstance(doc, PolicyDocument)
        assert doc.tools is None

    def test_unparseable_target_skipped(self):
        rule = _rule("tool:send_email", PolicyEffect.DENY)
        rule.target = "garbage"
        doc = rules_to_document([rule])
        assert doc.tools is None

    def test_combined_rules_produce_full_document(self):
        doc = rules_to_document(
            [
                _rule("spend", PolicyEffect.CAP, amount_usd="100.00", period="month"),
                _rule("tool:danger", PolicyEffect.DENY),
                _rule("tool:approve_me", PolicyEffect.APPROVAL),
                _rule("content", PolicyEffect.SAFETY, prompt_injection=True),
            ]
        )
        assert Decimal(str(doc.budget.monthly_spend_cap_usd)) == Decimal("100.00")
        assert doc.tools.denied == ["danger"]
        assert "approve_me" in doc.approval.escalation_rules
        assert doc.content_safety.prompt_injection_detection_enabled is True
