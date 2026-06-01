"""Contract tests for the governance policy migration."""

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
QQ1 = APP_ROOT / "alembic/versions/qq1_add_governance_policies.py"
RR1 = APP_ROOT / "alembic/versions/rr1_drop_workspace_settings.py"


def test_qq1_creates_both_governance_tables():
    sql = QQ1.read_text()

    assert 'op.create_table(\n        "governance_policies"' in sql
    assert 'op.create_table(\n        "task_policy_snapshots"' in sql


def test_qq1_has_no_backfill_from_workspace_settings():
    """qq1 must not backfill from workspace_settings — that table is dropped in rr1."""
    sql = QQ1.read_text()

    assert "FROM workspace_settings" not in sql
    assert "monthly_cap_usd" not in sql


def test_rr1_drops_workspace_settings_table():
    sql = RR1.read_text()

    assert 'op.drop_table("workspace_settings")' in sql
    assert 'down_revision: str | None = "qq1_add_governance_policies"' in sql
