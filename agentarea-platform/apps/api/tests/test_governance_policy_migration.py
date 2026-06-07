"""Contract + decompose tests for the governance policy unification migration."""

import importlib.util
from pathlib import Path

from agentarea_governance.domain.rules import (
    PolicyEffect,
    PolicyRule,
    PolicySubjectType,
    rules_to_document,
)

APP_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    APP_ROOT / "alembic/versions/20260605_1100_unify_governance_policy_rules.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("_gov_unify_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_creates_policies_and_drops_governance_policies():
    sql = MIGRATION.read_text()
    assert 'op.create_table(\n        "policies"' in sql
    assert 'op.drop_table("governance_policies")' in sql
    assert 'down_revision: str = "20260605_1000_add_workspace_slug"' in sql


def test_migration_data_migrates_from_governance_policies():
    sql = MIGRATION.read_text()
    assert "FROM governance_policies" in sql
    assert "INSERT INTO policies" in sql


def test_downgrade_recreates_governance_policies():
    sql = MIGRATION.read_text()
    assert 'op.create_table(\n        "governance_policies"' in sql
    assert 'op.drop_table("policies")' in sql


def test_decompose_then_compile_roundtrips_known_fields():
    """The decompose inverse of the compiler must round-trip a known document."""
    module = _load_migration()
    document = {
        "budget": {
            "monthly_spend_cap_usd": "100.00",
            "run_budget_usd": "5.00",
            "service_budget_usd": "2.00",
        },
        "tokens": {"max_tokens": 1000},
        "tools": {"allowed": ["search"], "denied": ["rm_rf"]},
        "approval": {
            "requires_human_approval": True,
            "escalation_rules": ["send_email"],
            "approvers": ["user:alice"],
        },
        "content_safety": {
            "prompt_injection_detection_enabled": True,
            "output_sanitizer_enabled": False,
        },
    }

    decomposed = module._decompose_document(document)
    rules = [
        PolicyRule(
            subject_type=PolicySubjectType.WORKSPACE,
            subject_id="ws-a",
            target=item["target"],
            effect=PolicyEffect(item["effect"]),
            params=item["params"],
        )
        for item in decomposed
    ]
    doc = rules_to_document(rules)

    assert str(doc.budget.monthly_spend_cap_usd) == "100.00"
    assert str(doc.budget.run_budget_usd) == "5.00"
    assert str(doc.budget.service_budget_usd) == "2.00"
    assert doc.tokens.max_tokens == 1000
    assert doc.tools.allowed == ["search"]
    assert doc.tools.denied == ["rm_rf"]
    assert doc.approval.requires_human_approval is True
    assert "send_email" in doc.approval.escalation_rules
    assert doc.approval.approvers == ["user:alice"]
    assert doc.content_safety.prompt_injection_detection_enabled is True
    assert doc.content_safety.output_sanitizer_enabled is False


def test_decompose_skips_unknown_keys():
    module = _load_migration()
    decomposed = module._decompose_document({"mystery": {"x": 1}})
    assert decomposed == []
