"""Stored local delegates are bound to their agent only where the name says which."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

MIGRATION = (
    Path(__file__).resolve().parents[1] / "alembic/versions/20261101_1200_delegate_agent_ids.py"
)

WS = "ws-a"


def _load_migration():
    spec = importlib.util.spec_from_file_location("_delegate_agent_ids", MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _upgrade(agents: list[tuple]) -> dict:
    """Run the upgrade over ``agents`` rows; the tools each UPDATE wrote, by agent id."""
    module = _load_migration()
    bind = MagicMock()
    bind.execute.return_value.fetchall.return_value = agents
    with patch.object(module.op, "get_bind", return_value=bind):
        module.upgrade()
    return {
        call.args[1]["id"]: json.loads(call.args[1]["tools"])
        for call in bind.execute.call_args_list[1:]
    }


def _agent(name: str, tools=None, status: str = "active", workspace: str = WS):
    return (str(uuid4()), workspace, name, status, json.dumps(tools) if tools else None)


def test_a_delegate_naming_one_live_agent_is_bound_to_it() -> None:
    target = _agent("reviewer")
    caller = _agent("lead", [{"type": "agent", "name": "reviewer"}])

    written = _upgrade([target, caller])

    assert written[caller[0]] == [
        {"type": "agent", "name": "reviewer", "settings": {"agent_id": target[0]}}
    ]


def test_a_shared_name_binds_nothing() -> None:
    caller = _agent("lead", [{"type": "agent", "name": "reviewer"}])

    written = _upgrade([_agent("reviewer"), _agent("reviewer"), caller])

    assert written == {}


def test_an_archived_or_foreign_namesake_does_not_count() -> None:
    target = _agent("reviewer")
    caller = _agent("lead", [{"type": "agent", "name": "reviewer"}])
    archived = _agent("reviewer", status="archived")
    foreign = _agent("reviewer", workspace="ws-b")

    written = _upgrade([target, archived, foreign, caller])

    assert written[caller[0]][0]["settings"]["agent_id"] == target[0]


def test_remote_and_already_bound_delegates_are_left_alone() -> None:
    caller = _agent(
        "lead",
        [
            {"type": "agent", "name": "reviewer", "settings": {"a2a_url": "https://x.example"}},
            {"type": "agent", "name": "reviewer", "settings": {"agent_id": "kept"}},
        ],
    )

    assert _upgrade([_agent("reviewer"), caller]) == {}
