"""Backfill the complete persisted policy baseline for legacy workspaces.

The first execution-policy backfill only enumerated the reified ``workspaces``
table. Older installations can still have valid workspace-scoped resources and
API keys whose workspace has not been reified, so those tenants were skipped.
They consequently had no persisted runtime budget, token, or execution limits
after implicit runtime defaults were removed.

This follow-up discovers both reified and active legacy workspaces, then inserts
each missing baseline dimension independently. Existing dimensions, including
disabled or partially configured rules, are preserved exactly; such an explicit
configuration remains fail-closed until an operator completes it.

Revision ID: 20260731_1200_policy_baseline
Revises: 20260731_1100_exec_policy
Create Date: 2026-07-31 12:00:00.000000
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_1200_policy_baseline"
down_revision: str | None = "20260731_1100_exec_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BASELINE_RULES = (
    (
        "spend",
        "cap",
        {"amount_usd": "500.00", "period": "month"},
        "month",
    ),
    (
        "spend",
        "cap",
        {"amount_usd": "50.00", "period": "run"},
        "run",
    ),
    (
        "tokens",
        "cap",
        {"max_tokens": 20_000_000, "max_tokens_per_call": 100_000},
        None,
    ),
    (
        "execution",
        "cap",
        {
            "max_model_turns": 100,
            "max_tool_calls_per_turn": 10,
            "max_tool_calls_total": 1000,
        },
        None,
    ),
    (
        "content",
        "safety",
        {"prompt_injection": True, "output_sanitizer": True},
        None,
    ),
)

_INSERT_MISSING_DIMENSION = sa.text(
    """
    WITH workspace_sources AS (
        SELECT id AS workspace_id, owner_user_id AS created_by
        FROM workspaces

        UNION ALL

        SELECT workspace_id, created_by
        FROM api_keys

        UNION ALL

        SELECT workspace_id, user_id AS created_by
        FROM workspace_memberships

        UNION ALL

        SELECT workspace_id, created_by
        FROM agents

        UNION ALL

        SELECT workspace_id, COALESCE(created_by, user_id) AS created_by
        FROM tasks
    ),
    workspace_targets AS (
        SELECT
            workspace_id,
            COALESCE(MIN(NULLIF(created_by, '')), workspace_id) AS created_by
        FROM workspace_sources
        WHERE workspace_id IS NOT NULL
          AND workspace_id <> ''
        GROUP BY workspace_id
    )
    INSERT INTO policies
        (id, workspace_id, created_by, subject_type, subject_id,
         target, effect, params, enabled, priority, created_at, updated_at)
    SELECT
        gen_random_uuid(), targets.workspace_id, targets.created_by,
        'workspace', targets.workspace_id,
        :target, :effect, CAST(:params AS jsonb), true, 0, now(), now()
    FROM workspace_targets AS targets
    WHERE NOT EXISTS (
        SELECT 1
        FROM policies AS policy
        WHERE policy.workspace_id = targets.workspace_id
          AND policy.subject_type = 'workspace'
          AND policy.subject_id = targets.workspace_id
          AND policy.target = :target
          AND policy.effect = :effect
          AND COALESCE(policy.params->>'period', '') = COALESCE(:period, '')
    )
    """
)


def upgrade() -> None:
    bind = op.get_bind()
    for target, effect, params, period in _BASELINE_RULES:
        bind.execute(
            _INSERT_MISSING_DIMENSION,
            {
                "target": target,
                "effect": effect,
                "params": json.dumps(params),
                "period": period,
            },
        )


def downgrade() -> None:
    # Rows are indistinguishable from equivalent rules created through the
    # governance API. Removing them could delete an operator-owned safety rule.
    pass
