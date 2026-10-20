"""Agents no longer carry the removed agentarea/decide toolset

The decide toolset is gone: a chat model handing a decision to a decision model
it could answer itself bought nothing. Decision models stay as trigger
conditions. A stored agent that still names the toolset would build nothing for
it and be refused on its next edit as naming an unknown code tool, so the entry
is dropped here.

Revision ID: 20261013_2200_drop_decide
Revises: 20261013_2100_item_pricing
Create Date: 2026-10-13 22:00:00.000000
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261013_2200_drop_decide"
down_revision: str | None = "20261013_2100_item_pricing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REMOVED = "agentarea/decide"


def _is_removed(tool: object) -> bool:
    return isinstance(tool, dict) and tool.get("type") == "code" and tool.get("name") == _REMOVED


def upgrade() -> None:
    bind = op.get_bind()
    agents = bind.execute(sa.text("SELECT id, tools FROM agents")).mappings().all()
    update = sa.text("UPDATE agents SET tools = CAST(:tools AS json) WHERE id = :id")

    for agent in agents:
        tools = agent["tools"]
        if isinstance(tools, str):
            try:
                tools = json.loads(tools)
            except ValueError, TypeError:
                continue
        if not isinstance(tools, list) or not any(_is_removed(tool) for tool in tools):
            continue
        kept = [tool for tool in tools if not _is_removed(tool)]
        bind.execute(update, {"tools": json.dumps(kept), "id": agent["id"]})


def downgrade() -> None:
    # The dropped entries named a toolset that no longer exists; nothing to restore.
    pass
