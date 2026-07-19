"""Move the per-tool approval toggle out of agent config into policy rules

The agent editor's "requires approval" toggle was stored on the agent's tools
JSON (code tool ``settings.requires_user_confirmation``; MCP
``allowed_tools[].requires_user_confirmation``) and enforced by nothing. Approval
is a governance decision, so it now lives in the policy engine as an agent-scoped
``PolicyRule(target="tool:<name>", effect="approval")`` — which the resolver
already folds into the snapshot the workflow gate reads.

This migration materializes those rules from existing config and strips the flag,
so rules become the single source of truth. It changes behavior: an agent whose
toggle was set now actually pauses for approval. That is the fix — the toggle was
ticked on purpose; it simply never did anything.

The target is the name the model calls, which the PDP judges: a code toolset
collapses its namespace (``agentarea/shell`` -> ``shell``); an MCP tool keeps the
raw name it advertises, which is exactly the ``allowed_tools`` entry.

Revision ID: 20260719_0100_approval_rules
Revises: 20260717_0200_backfill_canon
Create Date: 2026-07-19 01:00:00.000000
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260719_0100_approval_rules"
down_revision: str | None = "20260717_0200_backfill_canon"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _targets_and_stripped(tools: object) -> tuple[set[str], list, bool]:
    """Approval targets plus the tools with every confirmation flag removed."""
    if not isinstance(tools, list):
        return set(), [], False
    targets: set[str] = set()
    changed = False
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        settings = tool.get("settings")
        if not isinstance(settings, dict):
            continue
        if tool.get("type") == "mcp":
            for perm in settings.get("allowed_tools") or []:
                if isinstance(perm, dict) and "requires_user_confirmation" in perm:
                    if perm.pop("requires_user_confirmation"):
                        name = perm.get("tool_name")
                        if name:
                            targets.add(f"tool:{name}")
                    changed = True
        elif "requires_user_confirmation" in settings:
            if settings.pop("requires_user_confirmation"):
                name = tool.get("name")
                if name:
                    targets.add(f"tool:{name.rsplit('/', 1)[-1]}")
            changed = True
    return targets, tools, changed


def upgrade() -> None:
    bind = op.get_bind()
    agents = (
        bind.execute(sa.text("SELECT id, workspace_id, created_by, tools FROM agents"))
        .mappings()
        .all()
    )

    insert = sa.text(
        """
        INSERT INTO policies
            (id, workspace_id, created_by, subject_type, subject_id,
             target, effect, params, enabled, priority)
        SELECT gen_random_uuid(), :workspace_id, :created_by, 'agent', :subject_id,
               :target, 'approval', '{}'::jsonb, true, 0
        WHERE NOT EXISTS (
            SELECT 1 FROM policies
            WHERE workspace_id = :workspace_id
              AND subject_type = 'agent'
              AND subject_id = :subject_id
              AND target = :target
              AND effect = 'approval'
        )
        """
    )
    strip = sa.text("UPDATE agents SET tools = CAST(:tools AS json) WHERE id = :id")

    for agent in agents:
        tools = agent["tools"]
        if isinstance(tools, str):
            try:
                tools = json.loads(tools)
            except (ValueError, TypeError):
                continue
        targets, stripped, changed = _targets_and_stripped(tools)
        for target in targets:
            bind.execute(
                insert,
                {
                    "workspace_id": agent["workspace_id"],
                    "created_by": agent["created_by"],
                    "subject_id": str(agent["id"]),
                    "target": target,
                },
            )
        if changed:
            bind.execute(strip, {"tools": json.dumps(stripped), "id": agent["id"]})


def downgrade() -> None:
    # Not reversible: the flag's original per-tool placement is not recoverable
    # from the rules alone once the config has been stripped, and the API now
    # reconstitutes the flag from these rules on read anyway.
    pass
