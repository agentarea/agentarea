"""Backfill persisted execution limits for existing workspaces.

Execution limits were added to the baseline policy data after some workspaces
already existed. New workspaces receive the rule during provisioning, but old
ones otherwise have no persisted source for the required runtime contract.

This migration inserts the baseline only when the workspace has no
workspace-scoped execution cap at all. Existing rules, including disabled or
partially configured rules, are left untouched so a migration cannot silently
override an operator's governance decision.

Revision ID: 20260731_1100_exec_policy
Revises: 20260727_0100_mcp_last_used
Create Date: 2026-07-31 11:00:00.000000
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_1100_exec_policy"
down_revision: str | None = "20260727_0100_mcp_last_used"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BASELINE_EXECUTION_PARAMS = {
    "max_model_turns": 100,
    "max_tool_calls_per_turn": 10,
    "max_tool_calls_total": 1000,
}


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO policies
                (id, workspace_id, created_by, subject_type, subject_id,
                 target, effect, params, enabled, priority,
                 created_at, updated_at)
            SELECT gen_random_uuid(), w.id, w.owner_user_id, 'workspace', w.id,
                   'execution', 'cap', CAST(:params AS jsonb), true, 0,
                   now(), now()
            FROM workspaces AS w
            WHERE NOT EXISTS (
                SELECT 1
                FROM policies AS p
                WHERE p.workspace_id = w.id
                  AND p.subject_type = 'workspace'
                  AND p.subject_id = w.id
                  AND p.target = 'execution'
                  AND p.effect = 'cap'
            )
            """
        ),
        {"params": json.dumps(_BASELINE_EXECUTION_PARAMS)},
    )


def downgrade() -> None:
    # Keep the safety contract. Once inserted, these rows are indistinguishable
    # from an equivalent rule created through the public governance API; deleting
    # them on rollback could remove a user's active policy.
    pass
