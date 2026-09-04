"""Contract tests for the execution-policy backfill migration."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/20260731_1100_backfill_execution_policy.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("_execution_policy_backfill", MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backfill_inserts_only_missing_workspace_execution_caps() -> None:
    module = _load_migration()
    bind = MagicMock()

    with patch.object(module.op, "get_bind", return_value=bind):
        module.upgrade()

    bind.execute.assert_called_once()
    statement, parameters = bind.execute.call_args.args
    sql = str(statement)

    assert "INSERT INTO policies" in sql
    assert "FROM workspaces AS w" in sql
    assert "WHERE NOT EXISTS" in sql
    assert "p.subject_type = 'workspace'" in sql
    assert "p.subject_id = w.id" in sql
    assert "p.target = 'execution'" in sql
    assert "p.effect = 'cap'" in sql
    assert json.loads(parameters["params"]) == {
        "max_model_turns": 100,
        "max_tool_calls_per_turn": 10,
        "max_tool_calls_total": 1000,
    }


def test_backfill_follows_current_migration_head() -> None:
    module = _load_migration()

    assert module.revision == "20260731_1100_exec_policy"
    assert module.down_revision == "20260727_0100_mcp_last_used"
    assert len(module.revision) <= 32
