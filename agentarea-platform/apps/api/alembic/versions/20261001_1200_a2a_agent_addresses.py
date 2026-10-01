"""A2A by agent address: keys bound to one agent, delegates stored by address

``api_keys.agent_id`` binds a key to one agent: it then reaches that agent over
A2A and nothing else, which makes it the key to hand to another workspace.

A remote delegate's ``a2a_url`` is now the agent's address, where its card is
discovered, not its JSON-RPC endpoint. Delegates that point at an AgentArea
endpoint (``.../v1/agents/<id>/a2a/rpc``) are rewritten to the agent path
under the same host, which serves that agent's card. Any other server's URL is
left as it is: what its card is published under cannot be known here.

Revision ID: 20261001_1200_a2a_agent_addrs
Revises: 20260927_1200_catalog_cleanup
Create Date: 2026-10-01 12:00:00.000000
"""

import json
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261001_1200_a2a_agent_addrs"
down_revision: str | None = "20260927_1200_catalog_cleanup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AGENTAREA_RPC = re.compile(r"(/v1/agents/[0-9a-fA-F-]{36})/a2a/rpc/?$")
_AGENTAREA_ADDRESS = re.compile(r"/v1/agents/[0-9a-fA-F-]{36}$")


def _rewrite_delegates(rewrite) -> None:
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
            url = settings.get("a2a_url") if isinstance(settings, dict) else None
            if not isinstance(url, str):
                continue
            new_url = rewrite(url)
            if new_url != url:
                settings["a2a_url"] = new_url
                changed = True
        if changed:
            bind.execute(
                sa.text("UPDATE agents SET tools = :tools WHERE id = :id"),
                {"tools": json.dumps(parsed), "id": agent_id},
            )


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_api_keys_agent_id", "api_keys", ["agent_id"])
    _rewrite_delegates(lambda url: _AGENTAREA_RPC.sub(r"\1", url))


def downgrade() -> None:
    op.drop_index("ix_api_keys_agent_id", table_name="api_keys")
    op.drop_column("api_keys", "agent_id")
    _rewrite_delegates(lambda url: f"{url}/a2a/rpc" if _AGENTAREA_ADDRESS.search(url) else url)
