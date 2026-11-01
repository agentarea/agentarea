"""Stored MCP tools are bound to their connection only where the name says which.

And a bundle's recorded reuse of an entity its installer did not create is no
longer trusted as the bundle's own.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

MIGRATION = (
    Path(__file__).resolve().parents[1] / "alembic/versions/20261101_1800_mcp_tools_by_id.py"
)

WS = "ws-a"


def _load_migration():
    spec = importlib.util.spec_from_file_location("_mcp_tools_by_id", MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Db:
    """Answers the migration's reads from fixed rows and records its writes."""

    def __init__(self, *, instances=(), agents=(), rules=(), bundles=(), creators=None):
        self.instances = list(instances)
        self.agents = list(agents)
        self.rules = list(rules)
        self.bundles = list(bundles)
        self.creators = creators or {}
        self.agent_tools: dict[str, list] = {}
        self.rule_targets: dict[str, str] = {}
        self.install_results: dict[str, dict] = {}

    def execute(self, statement, params=None):
        sql = str(statement)
        rows: list = []
        scalar = None
        if sql.startswith("SELECT id, workspace_id, name, managed_by, created_by FROM mcp_"):
            rows = self.instances
        elif sql.startswith("SELECT id, workspace_id, created_by, tools FROM agents"):
            rows = self.agents
        elif sql.startswith("SELECT id, target FROM policies"):
            rows = [
                (rule_id, target)
                for rule_id, agent, target in self.rules
                if agent == params["agent"]
            ]
        elif sql.startswith("SELECT id, workspace_id, created_by, install_result"):
            rows = self.bundles
        elif sql.startswith("SELECT created_by FROM"):
            scalar = self.creators.get(params["id"])
        elif sql.startswith("UPDATE agents"):
            self.agent_tools[params["id"]] = json.loads(params["tools"])
        elif sql.startswith("UPDATE policies"):
            self.rule_targets[params["id"]] = params["target"]
        elif sql.startswith("UPDATE installed_bundles"):
            self.install_results[params["id"]] = json.loads(params["result"])
        return SimpleNamespace(fetchall=lambda: rows, scalar=lambda: scalar)


def _upgrade(db: _Db) -> _Db:
    module = _load_migration()
    bind = MagicMock()
    bind.execute.side_effect = db.execute
    with patch.object(module.op, "get_bind", return_value=bind):
        module.upgrade()
    return db


def _instance(name: str, workspace: str = WS, managed_by: str | None = None, by: str = "u"):
    return (str(uuid4()), workspace, name, managed_by, by)


def _agent(tools: list, workspace: str = WS, by: str = "u"):
    return (str(uuid4()), workspace, by, json.dumps(tools))


def test_a_tool_naming_one_connection_is_bound_to_it_and_its_approval_follows() -> None:
    github = _instance("github")
    agent = _agent([{"type": "mcp", "name": "github"}])
    rule = (str(uuid4()), agent[0], "tool:mcp:github:push")

    db = _upgrade(
        _Db(instances=[github, _instance("github", "ws-b")], agents=[agent], rules=[rule])
    )

    assert db.agent_tools[agent[0]] == [{"type": "mcp", "name": github[0]}]
    assert db.rule_targets == {rule[0]: f"tool:mcp:{github[0]}:push"}


def test_a_shared_or_missing_name_binds_nothing() -> None:
    agent = _agent([{"type": "mcp", "name": "github"}, {"type": "mcp", "name": "linear"}])

    db = _upgrade(_Db(instances=[_instance("github"), _instance("github")], agents=[agent]))

    assert db.agent_tools == {}


def test_a_name_only_someone_elses_connection_carries_binds_nothing() -> None:
    agent = _agent([{"type": "mcp", "name": "github"}])

    db = _upgrade(_Db(instances=[_instance("github", by="someone-else")], agents=[agent]))

    assert db.agent_tools == {}


def test_a_platform_connection_counts_in_every_workspace() -> None:
    gateway = _instance("tools", workspace="platform", managed_by="platform", by="operator")
    agent = _agent([{"type": "mcp", "name": "tools"}])

    db = _upgrade(_Db(instances=[gateway], agents=[agent]))

    assert db.agent_tools[agent[0]] == [{"type": "mcp", "name": gateway[0]}]


def test_a_bound_tool_is_left_alone() -> None:
    github = _instance("github")
    agent = _agent([{"type": "mcp", "name": github[0]}])

    assert _upgrade(_Db(instances=[github], agents=[agent])).agent_tools == {}


def test_a_recorded_reuse_of_someone_elses_entity_loses_its_id() -> None:
    own, foreign, created = str(uuid4()), str(uuid4()), str(uuid4())
    result = {
        "entities": [
            {"kind": "agent", "key": "lead", "action": "reused", "id": foreign},
            {"kind": "skill", "key": "sk", "action": "reused", "id": own},
            {"kind": "mcp", "key": "gh", "action": "created", "id": created},
        ]
    }
    bundle = (str(uuid4()), WS, "installer", json.dumps(result))

    db = _upgrade(_Db(bundles=[bundle], creators={own: "installer", foreign: "someone-else"}))

    entities = db.install_results[bundle[0]]["entities"]
    assert [entity["id"] for entity in entities] == [None, own, created]
