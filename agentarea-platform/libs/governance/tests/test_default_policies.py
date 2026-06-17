"""Tests for baseline default-policy provisioning."""

import pytest

from agentarea_governance.application.defaults import (
    default_policy_rules,
    provision_default_policies,
)
from agentarea_governance.domain.rules import PolicyEffect, PolicySubjectType


def test_shipped_defaults_are_workspace_scoped_and_sane():
    rules = default_policy_rules("ws-123")

    assert rules, "expected the shipped YAML to declare default policies"
    for rule in rules:
        assert rule.subject_type == PolicySubjectType.WORKSPACE
        assert rule.subject_id == "ws-123"
        assert rule.enabled is True

    pairs = {(rule.target, rule.effect) for rule in rules}
    assert ("spend", PolicyEffect.CAP) in pairs
    assert ("tokens", PolicyEffect.CAP) in pairs
    assert ("content", PolicyEffect.SAFETY) in pairs
    # Approval is intentionally NOT a default.
    assert PolicyEffect.APPROVAL not in {rule.effect for rule in rules}


def test_missing_config_file_yields_no_rules(tmp_path):
    assert default_policy_rules("ws-x", path=tmp_path / "absent.yaml") == []


def test_custom_config_path_overrides_defaults(tmp_path):
    cfg = tmp_path / "custom.yaml"
    cfg.write_text(
        "version: 1\n"
        "policies:\n"
        "  - target: tokens\n"
        "    effect: cap\n"
        "    params: { max_tokens: 5 }\n"
    )
    rules = default_policy_rules("ws-1", path=cfg)
    assert len(rules) == 1
    assert rules[0].target == "tokens"
    assert rules[0].params == {"max_tokens": 5}


class _FakeService:
    """In-memory stand-in for GovernancePolicyService."""

    def __init__(self):
        self.rules = []

    async def list_rules(self, *, subject_type=None, subject_id=None, **_kwargs):
        return [
            r
            for r in self.rules
            if (subject_id is None or r.subject_id == subject_id)
            and (subject_type is None or r.subject_type == subject_type)
        ]

    async def create_rule(self, *, rule, subject_id):  # noqa: ARG002
        self.rules.append(rule)
        return rule


@pytest.mark.asyncio
async def test_provision_seeds_then_is_idempotent():
    service = _FakeService()

    first = await provision_default_policies(service, "ws-1")
    assert first, "first provisioning should seed defaults"

    second = await provision_default_policies(service, "ws-1")
    assert second == [], "second provisioning must be a no-op"

    assert len(service.rules) == len(first)


@pytest.mark.asyncio
async def test_provision_fills_only_missing_dimensions():
    service = _FakeService()
    defaults = default_policy_rules("ws-2")
    # User already configured the monthly spend cap (with their own amount).
    monthly = next(
        r for r in defaults if r.target == "spend" and r.params.get("period") == "month"
    )
    monthly.params = {"amount_usd": "123.45", "period": "month"}
    service.rules.append(monthly)

    created = await provision_default_policies(service, "ws-2")

    # The monthly cap is left untouched; the remaining dimensions are added.
    created_keys = {(r.target, r.params.get("period")) for r in created}
    assert ("spend", "month") not in created_keys  # not re-seeded
    assert ("spend", "run") in created_keys
    assert ("tokens", None) in created_keys
    assert ("content", None) in created_keys

    # User's amount is preserved.
    kept = next(
        r for r in service.rules if r.target == "spend" and r.params.get("period") == "month"
    )
    assert kept.params["amount_usd"] == "123.45"

    # And re-running is now a full no-op.
    assert await provision_default_policies(service, "ws-2") == []
