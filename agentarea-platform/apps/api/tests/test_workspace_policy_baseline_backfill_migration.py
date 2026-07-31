"""Contract tests for the legacy-workspace policy baseline backfill."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/20260731_1200_backfill_workspace_policy_baseline.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("_workspace_policy_baseline", MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backfill_discovers_reified_and_legacy_workspaces() -> None:
    module = _load_migration()
    bind = MagicMock()

    with patch.object(module.op, "get_bind", return_value=bind):
        module.upgrade()

    assert bind.execute.call_count == 5
    sql = str(bind.execute.call_args_list[0].args[0])

    assert "FROM workspaces" in sql
    assert "FROM api_keys" in sql
    assert "FROM workspace_memberships" in sql
    assert "FROM agents" in sql
    assert "FROM tasks" in sql
    assert "workspace_id <> ''" in sql
    assert "WHERE NOT EXISTS" in sql
    assert "policy.subject_type = 'workspace'" in sql
    assert "policy.subject_id = targets.workspace_id" in sql
    assert "policy.params->>'period'" in sql


def test_backfill_inserts_the_complete_persisted_baseline() -> None:
    module = _load_migration()
    bind = MagicMock()

    with patch.object(module.op, "get_bind", return_value=bind):
        module.upgrade()

    inserted = [
        {
            "target": call.args[1]["target"],
            "effect": call.args[1]["effect"],
            "params": json.loads(call.args[1]["params"]),
            "period": call.args[1]["period"],
        }
        for call in bind.execute.call_args_list
    ]

    assert inserted == [
        {
            "target": "spend",
            "effect": "cap",
            "params": {"amount_usd": "500.00", "period": "month"},
            "period": "month",
        },
        {
            "target": "spend",
            "effect": "cap",
            "params": {"amount_usd": "50.00", "period": "run"},
            "period": "run",
        },
        {
            "target": "tokens",
            "effect": "cap",
            "params": {"max_tokens": 20_000_000, "max_tokens_per_call": 100_000},
            "period": None,
        },
        {
            "target": "execution",
            "effect": "cap",
            "params": {
                "max_model_turns": 100,
                "max_tool_calls_per_turn": 10,
                "max_tool_calls_total": 1000,
            },
            "period": None,
        },
        {
            "target": "content",
            "effect": "safety",
            "params": {"prompt_injection": True, "output_sanitizer": True},
            "period": None,
        },
    ]


def test_backfill_follows_current_migration_head() -> None:
    module = _load_migration()

    assert module.revision == "20260731_1200_policy_baseline"
    assert module.down_revision == "20260731_1100_exec_policy"
    assert len(module.revision) <= 32
