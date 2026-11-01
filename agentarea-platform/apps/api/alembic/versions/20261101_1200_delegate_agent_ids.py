"""Delegates reach an agent by id: bind each stored local delegate to its agent

A local delegate was resolved by name at every run, and agent names are not
unique: the newest agent under a name took every delegation to it. Each local
delegate (one without an ``a2a_url``) now carries ``settings.agent_id``. A
delegate whose name names exactly one live agent of its workspace is bound to
it here; one whose name is shared or names no agent is left unbound, and the
runtime offers it to no one until the agent is saved with a chosen delegate.

Revision ID: 20261101_1200_delegate_ids
Revises: 20261031_2000_egress_exits
Create Date: 2026-11-01 12:00:00.000000
"""

import json
import logging
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20261101_1200_delegate_ids"
down_revision: str | None = "20261031_2000_egress_exits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    bind = op.get_bind()
    agents = bind.execute(
        sa.text("SELECT id, workspace_id, name, status, tools FROM agents")
    ).fetchall()
    live_by_name: dict[tuple[str, str], list[str]] = {}
    for agent_id, workspace_id, name, status, _tools in agents:
        if status != "archived":
            live_by_name.setdefault((str(workspace_id), name), []).append(str(agent_id))

    bound = unbound = 0
    for agent_id, workspace_id, _name, _status, tools in agents:
        parsed = json.loads(tools) if isinstance(tools, str) else tools
        if not isinstance(parsed, list):
            continue
        changed = False
        for tool in parsed:
            if not isinstance(tool, dict) or tool.get("type") != "agent":
                continue
            raw_settings = tool.get("settings")
            settings: dict[str, Any] = raw_settings if isinstance(raw_settings, dict) else {}
            if settings.get("a2a_url") or settings.get("agent_id"):
                continue
            matches = live_by_name.get((str(workspace_id), str(tool.get("name"))), [])
            if len(matches) != 1:
                unbound += 1
                continue
            tool["settings"] = {**settings, "agent_id": matches[0]}
            changed = True
            bound += 1
        if changed:
            bind.execute(
                sa.text("UPDATE agents SET tools = :tools WHERE id = :id"),
                {"tools": json.dumps(parsed), "id": agent_id},
            )
    logger.info(
        "Bound %d local delegates to their agent; %d name a shared or missing agent and "
        "stay unbound until their agent is saved",
        bound,
        unbound,
    )


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, tools FROM agents WHERE tools IS NOT NULL")).fetchall()
    for agent_id, tools in rows:
        parsed = json.loads(tools) if isinstance(tools, str) else tools
        if not isinstance(parsed, list):
            continue
        changed = False
        for tool in parsed:
            if not isinstance(tool, dict) or tool.get("type") != "agent":
                continue
            settings = tool.get("settings")
            if isinstance(settings, dict) and "agent_id" in settings:
                settings.pop("agent_id")
                changed = True
        if changed:
            bind.execute(
                sa.text("UPDATE agents SET tools = :tools WHERE id = :id"),
                {"tools": json.dumps(parsed), "id": agent_id},
            )
