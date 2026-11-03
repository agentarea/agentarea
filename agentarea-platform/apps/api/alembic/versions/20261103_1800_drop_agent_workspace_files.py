"""Agents no longer carry the agent-side agentarea/workspace_files toolset

Its list and delete repeated the files tool and the shell over the same
sandbox, and its download path pointed at a file that was not there until the
task published it. A file reaches the user from /workspace/outputs/ instead,
with the download button its artifact card already has. The MCP toolset of the
same name, which clients carry, is unaffected. A stored agent that still names
it would build nothing for it and be refused on its next edit as naming an
unknown code tool, so the entry is dropped here.

Revision ID: 20261103_1800_drop_ws_files
Revises: 20261103_1300_first_party
Create Date: 2026-11-03 18:00:00.000000
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_1800_drop_ws_files"
down_revision: str | None = "20261103_1300_first_party"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REMOVED = "agentarea/workspace_files"


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
    # The dropped entries named a toolset agents no longer have; nothing to restore.
    pass
