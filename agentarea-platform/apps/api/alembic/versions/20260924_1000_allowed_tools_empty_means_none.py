"""An empty allowed_tools list now means no tools; keep existing agents as they were

An agent's MCP or OpenAPI attachment carries ``settings.allowed_tools``. Until now
the runtime filtered only on a non-empty list, so ``[]`` meant "every tool of the
server" — and the editor wrote ``[]`` both when the user never restricted the
server and when they switched every tool off. From this revision ``[]`` means no
tools and ``null`` means every tool, the way the policy engine already
distinguishes an absent allowlist from an empty one.

Stored ``[]`` values were written under the old meaning, so they become ``null``:
every existing agent keeps exactly the tools it had. An agent whose user had
switched every tool off keeps them all, as it did before; that intent was never
recorded distinctly and cannot be recovered.

Revision ID: 20260924_1000_allowed_tools_none
Revises: 20260919_1000_catalog_rank
Create Date: 2026-09-24 10:00:00.000000
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_1000_allowed_tools_none"
down_revision: str | None = "20260919_1000_catalog_rank"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RESTRICTABLE = {"mcp", "openapi"}


def _empty_allowlists_to_null(tools: object) -> tuple[object, bool]:
    if not isinstance(tools, list):
        return tools, False
    changed = False
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") not in _RESTRICTABLE:
            continue
        settings = tool.get("settings")
        if isinstance(settings, dict) and settings.get("allowed_tools") == []:
            settings["allowed_tools"] = None
            changed = True
    return tools, changed


def upgrade() -> None:
    bind = op.get_bind()
    agents = bind.execute(sa.text("SELECT id, tools FROM agents")).mappings().all()
    update = sa.text("UPDATE agents SET tools = CAST(:tools AS json) WHERE id = :id")

    for agent in agents:
        tools = agent["tools"]
        if isinstance(tools, str):
            try:
                tools = json.loads(tools)
            except (ValueError, TypeError):
                continue
        tools, changed = _empty_allowlists_to_null(tools)
        if changed:
            bind.execute(update, {"tools": json.dumps(tools), "id": agent["id"]})


def downgrade() -> None:
    # Nothing to undo: ``null`` meant "every tool" under the old reading too.
    pass
