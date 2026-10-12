"""cost_entries: the spend ledger, one row per paid line of a task

Run budgets, monthly caps and task breakdowns were sums over each task's
``result.own_cost``: model spend only, one number per task, with nothing to show
what it was made of. The ledger keeps every paid line on its own row (an LLM
call, a compaction, a platform model a tool ran, a wallet payment a tool made)
with the evidence it was priced from, and every total becomes a sum of rows.

The upgrade backfills the ledger from the events that already carry each paid
line: ``llm.call.completed`` (``cost``) and ``tool.result`` (``model_cost``,
``service_cost``). Model lines keep ``currency`` NULL because the events do not
name it; they were priced in the deployment's billing currency. Wallet payments
are USD.

Revision ID: 20261008_1200_cost_entries
Revises: 20261006_1200_tool_call_approval
Create Date: 2026-10-08 12:00:00.000000
"""

# Every interpolated value below is a module constant, never input.
# ruff: noqa: S608

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261008_1200_cost_entries"
down_revision: str | None = "20261006_1200_tool_call_approval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NUMERIC = r"'^\s*[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?\s*$'"


def _amount(field: str) -> str:
    return f"CASE WHEN e.data->>'{field}' ~ {_NUMERIC} THEN (e.data->>'{field}')::numeric END"


_COLUMNS = (
    "id, workspace_id, created_by, event_id, category, task_id, agent_id, subject_type, "
    "subject_id, subject_name, call_ref, amount, currency, provider_cost_usd, managed_by, "
    "source, evidence, occurred_at"
)
_TOOL_EVIDENCE = (
    "'source', e.data->'source', 'server_name', e.data->'server_name', "
    "'iteration', e.data->'iteration'"
)

# Idempotent: a line already stored for its (event, category) is skipped.
BACKFILL_SQL = (
    f"""
    INSERT INTO cost_entries ({_COLUMNS})
    SELECT gen_random_uuid(), e.workspace_id, e.created_by, e.id, 'model', e.task_id,
           t.agent_id, 'model_instance', e.data->>'model_id', e.data->>'model_name', NULL,
           {_amount("cost")}, NULL, {_amount("provider_cost_usd")}, e.data->>'managed_by',
           'token_pricing',
           jsonb_strip_nulls(jsonb_build_object(
               'iteration', e.data->'iteration',
               'purpose', e.data->'purpose',
               'prompt_tokens', e.data->'usage'->'usage'->'prompt_tokens',
               'completion_tokens', e.data->'usage'->'usage'->'completion_tokens',
               'total_tokens', e.data->'usage'->'usage'->'total_tokens'
           )),
           e.timestamp
    FROM task_events e
    LEFT JOIN tasks t ON t.id = e.task_id
    WHERE e.event_type = 'llm.call.completed' AND {_amount("cost")} > 0
    ON CONFLICT (event_id, category) DO NOTHING
    """,
    f"""
    INSERT INTO cost_entries ({_COLUMNS})
    SELECT gen_random_uuid(), e.workspace_id, e.created_by, e.id, 'model', e.task_id,
           t.agent_id, 'tool', e.data->>'server_instance_id', e.data->>'tool_name',
           e.data->>'tool_call_id', {_amount("model_cost")}, NULL, NULL, NULL,
           'tool_reported', jsonb_strip_nulls(jsonb_build_object({_TOOL_EVIDENCE})),
           e.timestamp
    FROM task_events e
    LEFT JOIN tasks t ON t.id = e.task_id
    WHERE e.event_type = 'tool.result' AND {_amount("model_cost")} > 0
    ON CONFLICT (event_id, category) DO NOTHING
    """,
    f"""
    INSERT INTO cost_entries ({_COLUMNS})
    SELECT gen_random_uuid(), e.workspace_id, e.created_by, e.id, 'service', e.task_id,
           t.agent_id, 'tool', e.data->>'server_instance_id', e.data->>'tool_name',
           e.data->>'tool_call_id', {_amount("service_cost")}, 'USD',
           {_amount("service_cost")}, NULL,
           CASE e.data->'payment'->>'protocol'
               WHEN 'x402' THEN 'x402' WHEN 'mpp' THEN 'mpp' ELSE 'tool_reported'
           END,
           jsonb_strip_nulls(jsonb_build_object(
               {_TOOL_EVIDENCE},
               'payment', NULLIF(jsonb_strip_nulls(jsonb_build_object(
                   'protocol', e.data->'payment'->'protocol',
                   'recipient', e.data->'payment'->'recipient',
                   'tx_hash', e.data->'payment'->'tx_hash',
                   'amount_usd', e.data->'payment'->'amount_usd'
               )), '{{}}'::jsonb)
           )),
           e.timestamp
    FROM task_events e
    LEFT JOIN tasks t ON t.id = e.task_id
    WHERE e.event_type = 'tool.result' AND {_amount("service_cost")} > 0
    ON CONFLICT (event_id, category) DO NOTHING
    """,
)


def upgrade() -> None:
    op.create_table(
        "cost_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_type", sa.String(32), nullable=False),
        sa.Column("subject_id", sa.String(255), nullable=True),
        sa.Column("subject_name", sa.String(255), nullable=True),
        sa.Column("call_ref", sa.String(255), nullable=True),
        sa.Column("amount", sa.Numeric(20, 12), nullable=False),
        sa.Column("currency", sa.String(8), nullable=True),
        sa.Column("provider_cost_usd", sa.Numeric(20, 12), nullable=True),
        sa.Column("managed_by", sa.String(32), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column(
            "evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", "category", name="uq_cost_entries_event_category"),
    )
    op.create_index("ix_cost_entries_workspace_id", "cost_entries", ["workspace_id"])
    op.create_index("ix_cost_entries_created_by", "cost_entries", ["created_by"])
    op.create_index("ix_cost_entries_task_id", "cost_entries", ["task_id"])
    op.create_index(
        "ix_cost_entries_workspace_occurred", "cost_entries", ["workspace_id", "occurred_at"]
    )
    op.create_index(
        "ix_cost_entries_agent_occurred",
        "cost_entries",
        ["workspace_id", "agent_id", "occurred_at"],
    )
    op.create_index(
        "ix_cost_entries_supersedes",
        "cost_entries",
        ["supersedes_id"],
        postgresql_where=sa.text("supersedes_id IS NOT NULL"),
    )

    for statement in BACKFILL_SQL:
        op.execute(statement)


def downgrade() -> None:
    op.drop_table("cost_entries")
