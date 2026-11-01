"""MCP tools reach a connection by id; a bundle reuses only what it installed

An agent's MCP tool could name its connection by name (bundle installs wrote
names), and the runtime took the first connection carrying it. Connection names
are not unique, so whoever added a second one under the name could take the
tool over. The runtime now reads an id only. A stored name that exactly one
connection the workspace sees carries is bound to that connection here when
the agent's creator added it or the platform supplies it, and the agent's
approval rules written for the name are rewritten for the id. Any other name
is left; the runtime offers no tool for it until the agent is saved with a
chosen connection.

A bundle install used to reuse any agent, connection or skill that carried the
bundle's name. Reuse now follows the ids an earlier install of the bundle
recorded, so a recorded reuse of an entity someone other than the bundle's
installer created loses its id here: the next install creates its own.

Revision ID: 20261101_1800_mcp_tool_ids
Revises: 20261101_1200_delegate_ids
Create Date: 2026-11-01 18:00:00.000000
"""

import json
import logging
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "20261101_1800_mcp_tool_ids"
down_revision: str | None = "20261101_1200_delegate_ids"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

_ENTITY_TABLES = {"agent": "agents", "mcp": "mcp_server_instances", "skill": "skills"}


def _is_uuid(value: object) -> bool:
    try:
        UUID(str(value))
    except ValueError:
        return False
    return True


def _parse(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _bind_mcp_tools(bind: Any) -> None:
    instances = bind.execute(
        sa.text("SELECT id, workspace_id, name, managed_by, created_by FROM mcp_server_instances")
    ).fetchall()
    # (id, creator), creator None for a platform connection anyone may use.
    own: dict[tuple[str, str], list[tuple[str, str | None]]] = {}
    platform: dict[str, list[tuple[str, str | None]]] = {}
    for instance_id, workspace_id, name, managed_by, created_by in instances:
        if managed_by == "platform":
            platform.setdefault(name, []).append((str(instance_id), None))
        else:
            own.setdefault((str(workspace_id), name), []).append((str(instance_id), created_by))

    agents = bind.execute(
        sa.text("SELECT id, workspace_id, created_by, tools FROM agents")
    ).fetchall()
    bound = unbound = 0
    for agent_id, workspace_id, agent_creator, tools in agents:
        parsed = _parse(tools)
        if not isinstance(parsed, list):
            continue
        renamed: dict[str, str] = {}
        for tool in parsed:
            if not isinstance(tool, dict) or tool.get("type") != "mcp":
                continue
            name = tool.get("name")
            if not isinstance(name, str) or not name or _is_uuid(name):
                continue
            matches = own.get((str(workspace_id), name), []) + platform.get(name, [])
            if len(matches) != 1 or matches[0][1] not in (None, agent_creator):
                unbound += 1
                continue
            tool["name"] = renamed[name] = matches[0][0]
            bound += 1
        if not renamed:
            continue
        bind.execute(
            sa.text("UPDATE agents SET tools = CAST(:tools AS json) WHERE id = :id"),
            {"tools": json.dumps(parsed), "id": agent_id},
        )
        rules = bind.execute(
            sa.text(
                "SELECT id, target FROM policies "
                "WHERE subject_type = 'agent' AND subject_id = :agent AND effect = 'approval'"
            ),
            {"agent": str(agent_id)},
        ).fetchall()
        for rule_id, target in rules:
            for name, instance_id in renamed.items():
                prefix = f"tool:mcp:{name}:"
                retargeted = f"tool:mcp:{instance_id}:{target[len(prefix) :]}"
                # The name rule still narrows the tool where the id form would not fit.
                if target.startswith(prefix) and len(retargeted) <= 255:
                    bind.execute(
                        sa.text("UPDATE policies SET target = :target WHERE id = :id"),
                        {"target": retargeted, "id": rule_id},
                    )
                    break
    logger.info(
        "Bound %d MCP tools to their connection; %d name no connection of their agent's "
        "creator alone and stay unbound until their agent is saved",
        bound,
        unbound,
    )


def _distrust_foreign_reuse(bind: Any) -> None:
    bundles = bind.execute(
        sa.text("SELECT id, workspace_id, created_by, install_result FROM installed_bundles")
    ).fetchall()
    for bundle_id, workspace_id, installer, install_result in bundles:
        result = _parse(install_result)
        entities = result.get("entities") if isinstance(result, dict) else None
        if not isinstance(entities, list):
            continue
        changed = False
        for entity in entities:
            if not isinstance(entity, dict) or entity.get("action") != "reused":
                continue
            table = _ENTITY_TABLES.get(str(entity.get("kind")))
            if table is None or not _is_uuid(entity.get("id")):
                continue
            creator = bind.execute(
                sa.text(f"SELECT created_by FROM {table} WHERE id = :id AND workspace_id = :ws"),  # noqa: S608
                {"id": str(entity["id"]), "ws": str(workspace_id)},
            ).scalar()
            if creator != installer:
                entity["id"] = None
                changed = True
        if changed:
            bind.execute(
                sa.text(
                    "UPDATE installed_bundles SET install_result = CAST(:result AS jsonb) WHERE id = :id"
                ),
                {"result": json.dumps(result), "id": bundle_id},
            )


def upgrade() -> None:
    bind = op.get_bind()
    _bind_mcp_tools(bind)
    _distrust_foreign_reuse(bind)


def downgrade() -> None:
    # Not reversible: once bound, a tool's id does not say whether it was
    # stored as a name, and an id reaches the same connection under either
    # revision.
    pass
