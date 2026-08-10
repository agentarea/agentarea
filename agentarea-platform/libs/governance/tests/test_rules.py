"""Tests for the unified policy rule model, parse_target, and the compiler."""

from decimal import Decimal

import pytest
from agentarea_governance.domain.policies import PolicyDocument
from agentarea_governance.domain.rules import (
    PolicyEffect,
    PolicyRule,
    PolicySubjectType,
    assert_enforceable,
    egress_allowlist_from_rules,
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
        doc = rules_to_document([_rule("spend", PolicyEffect.CAP, amount_usd="2.50", period="run")])
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

    def test_tool_scoped_approvers_go_to_approvers_by_tool(self):
        # A tool-scoped approval rule keeps its approvers attached to that tool,
        # not flattened into the global list — so "tool A signed by alice" and
        # "tool B signed by bob" stay distinct.
        doc = rules_to_document(
            [_rule("tool:launch_task", PolicyEffect.APPROVAL, approvers=["user:alice"])]
        )
        assert doc.approval.approvers_by_tool == {"launch_task": ["user:alice"]}
        assert "launch_task" in doc.approval.escalation_rules
        assert doc.approval.approvers == []

    def test_two_tools_keep_separate_approver_lists(self):
        doc = rules_to_document(
            [
                _rule("tool:launch_task", PolicyEffect.APPROVAL, approvers=["user:alice"]),
                _rule("tool:delete_file", PolicyEffect.APPROVAL, approvers=["user:bob"]),
            ]
        )
        assert doc.approval.approvers_by_tool == {
            "launch_task": ["user:alice"],
            "delete_file": ["user:bob"],
        }
        assert doc.approval.approvers == []

    def test_global_approval_approvers_populate_the_flat_list(self):
        doc = rules_to_document([_rule("*", PolicyEffect.APPROVAL, approvers=["user:root"])])
        assert doc.approval.requires_human_approval is True
        assert doc.approval.approvers == ["user:root"]
        assert doc.approval.approvers_by_tool == {}

    def test_wildcard_tool_approvers_populate_the_flat_list(self):
        doc = rules_to_document([_rule("tool:*", PolicyEffect.APPROVAL, approvers=["user:root"])])
        assert doc.approval.approvers == ["user:root"]
        assert doc.approval.approvers_by_tool == {}

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


class TestEgressRules:
    def test_egress_rule_does_not_compile_into_runtime_document(self):
        # Egress is enforced at the container network layer (enterprise), never
        # in the in-process runtime document.
        doc = rules_to_document(
            [_rule("mcp:github", PolicyEffect.EGRESS, allowed_hosts=["*.github.com"])]
        )
        assert doc == PolicyDocument()

    def test_allowlist_extraction_by_target(self):
        rules = [
            _rule(
                "mcp:github", PolicyEffect.EGRESS, allowed_hosts=["*.github.com", "api.github.com"]
            ),
            _rule("mcp:slack", PolicyEffect.EGRESS, allowed_hosts=["slack.com"]),
            _rule("tool:send_email", PolicyEffect.ALLOW),  # non-egress ignored
        ]
        assert egress_allowlist_from_rules(rules) == {
            "mcp:github": ["*.github.com", "api.github.com"],
            "mcp:slack": ["slack.com"],
        }

    def test_allowlist_dedupes_and_merges_same_target(self):
        rules = [
            _rule("mcp:github", PolicyEffect.EGRESS, allowed_hosts=["*.github.com"]),
            _rule(
                "mcp:github", PolicyEffect.EGRESS, allowed_hosts=["*.github.com", "raw.github.com"]
            ),
        ]
        assert egress_allowlist_from_rules(rules) == {
            "mcp:github": ["*.github.com", "raw.github.com"]
        }

    def test_disabled_egress_rule_skipped(self):
        rule = _rule("mcp:github", PolicyEffect.EGRESS, allowed_hosts=["*.github.com"])
        rule.enabled = False
        assert egress_allowlist_from_rules([rule]) == {}

    def test_declared_empty_allowlist_is_default_deny(self):
        # A target present with an empty list = declared, nothing allowed.
        assert egress_allowlist_from_rules(
            [_rule("mcp:github", PolicyEffect.EGRESS, allowed_hosts=[])]
        ) == {"mcp:github": []}

    def test_malformed_allowed_hosts_skipped(self):
        assert (
            egress_allowlist_from_rules(
                [_rule("mcp:github", PolicyEffect.EGRESS, allowed_hosts="not-a-list")]
            )
            == {}
        )


class TestAssertEnforceable:
    """assert_enforceable must mirror the compiler: accept exactly what compiles
    to a runtime effect (plus egress as opaque data core stores for enterprise),
    and reject everything the compiler would silently skip — so the write API can
    never 201 a rule that then never enforces (fail-open)."""

    @pytest.mark.parametrize(
        "target,effect,params",
        [
            ("tool:send_email", PolicyEffect.DENY, {}),
            ("tool:web_fetch", PolicyEffect.ALLOW, {}),
            ("spend", PolicyEffect.CAP, {"amount_usd": 10}),
            ("spend", PolicyEffect.CAP, {"amount_usd": 5, "period": "run"}),
            ("service", PolicyEffect.CAP, {"amount_usd": 3}),
            ("tokens", PolicyEffect.CAP, {"max_tokens": 1000}),
            ("tokens", PolicyEffect.CAP, {"max_tokens_per_call": 100}),
            ("execution", PolicyEffect.CAP, {"max_model_turns": 10}),
            ("*", PolicyEffect.APPROVAL, {}),
            ("tool:*", PolicyEffect.APPROVAL, {}),
            ("tool:send_email", PolicyEffect.APPROVAL, {}),
            ("content", PolicyEffect.SAFETY, {"prompt_injection": True}),
            ("content", PolicyEffect.SAFETY, {"output_sanitizer": True}),
            ("mcp:github", PolicyEffect.EGRESS, {"allowed_hosts": ["*.github.com"]}),
            ("mcp:github", PolicyEffect.EGRESS, {}),
        ],
    )
    def test_accepts_enforceable_rules(self, target, effect, params):
        assert_enforceable(_rule(target, effect, **params))

    @pytest.mark.parametrize(
        "target,effect,params",
        [
            ("tool:*", PolicyEffect.DENY, {}),
            ("tool", PolicyEffect.DENY, {}),
            ("tool:*", PolicyEffect.ALLOW, {}),
            ("model:gpt-4", PolicyEffect.DENY, {}),
            ("mcp:x", PolicyEffect.DENY, {}),
            ("skill:x", PolicyEffect.ALLOW, {}),
            ("tool:send_email", PolicyEffect.CAP, {}),
            ("tokens", PolicyEffect.CAP, {}),
            ("execution", PolicyEffect.CAP, {}),
            ("spend", PolicyEffect.CAP, {}),
            ("spend", PolicyEffect.CAP, {"amount_usd": "abc"}),
            ("spend", PolicyEffect.CAP, {"amount_usd": 1, "period": "week"}),
            ("model:x", PolicyEffect.APPROVAL, {}),
            ("content", PolicyEffect.SAFETY, {}),
            ("tool:x", PolicyEffect.SAFETY, {}),
        ],
    )
    def test_rejects_unenforceable_rules(self, target, effect, params):
        with pytest.raises(ValueError):
            assert_enforceable(_rule(target, effect, **params))

    def test_rejects_unknown_target_kind(self):
        with pytest.raises(ValueError):
            assert_enforceable(_rule("bogus:x", PolicyEffect.DENY))

    def test_rejects_group_subject(self):
        rule = PolicyRule(
            subject_type=PolicySubjectType.GROUP,
            subject_id="grp-a",
            target="tool:send_email",
            effect=PolicyEffect.DENY,
        )
        with pytest.raises(ValueError):
            assert_enforceable(rule)

    def test_rejects_condition(self):
        rule = PolicyRule(
            subject_type=PolicySubjectType.WORKSPACE,
            subject_id="ws-a",
            target="tool:send_email",
            effect=PolicyEffect.DENY,
            condition="request.time < 17",
        )
        with pytest.raises(ValueError):
            assert_enforceable(rule)
