"""Agent revisions and experiments; every run pinned to the revision it ran

``agent_revisions`` holds immutable snapshots of what an agent runs. The
``agents`` executable columns stay as the materialized copy of the revision its
``current_revision_id`` points at. ``tasks.agent_revision_id`` pins a run to
the revision it was submitted against, and ``tasks.experiment_id`` marks runs
an experiment assigned. ``agent_experiments`` splits traffic between the
serving revision and one candidate; at most one runs per agent.

Revision ID: 20261003_1200_agent_revisions
Revises: 20261003_1100_merge_heads
Create Date: 2026-10-03 12:00:00.000000
"""

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261003_1200_agent_revisions"
down_revision: str | None = "20261003_1100_merge_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# A frozen copy of compute_agent_config_hash (v3) as of this migration, so the
# backfilled revisions hash exactly like the ones the service records later.
_HASH_VERSION = "v3"
_HASHED_FIELDS = ("instruction", "model_id", "tools", "planning", "a2ui_enabled")


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _canonical(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return sorted((_canonical(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    return value


def _config_hash(spec: dict[str, Any]) -> str:
    payload = {field: _canonical(spec.get(field)) for field in _HASHED_FIELDS}
    payload["skill_ids"] = sorted(str(s) for s in spec["skill_ids"])
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"{_HASH_VERSION}:{hashlib.sha256(encoded).hexdigest()}"


def _backfill() -> None:
    """One revision per existing agent, from its current row; history is not rebuilt."""
    bind = op.get_bind()
    skills: dict[Any, list[str]] = {}
    for agent_id, skill_id in bind.execute(sa.text("SELECT agent_id, skill_id FROM agent_skills")):
        skills.setdefault(agent_id, []).append(str(skill_id))
    agents = bind.execute(
        sa.text(
            "SELECT id, instruction, model_id, tools, planning, a2ui_enabled, workspace_id, "
            "created_by FROM agents"
        )
    ).fetchall()
    now = datetime.now()
    for row in agents:
        tools = json.loads(row.tools) if isinstance(row.tools, str) else row.tools
        spec = {
            "instruction": row.instruction,
            "model_id": row.model_id,
            "tools": [t for t in tools if isinstance(t, dict)] if isinstance(tools, list) else [],
            "skill_ids": sorted(skills.get(row.id, [])),
            "planning": row.planning,
            "a2ui_enabled": row.a2ui_enabled,
        }
        revision_id = uuid.uuid4()
        bind.execute(
            sa.text(
                "INSERT INTO agent_revisions (id, agent_id, number, parent_revision_id, spec, "
                "config_hash, status, origin, evidence, workspace_id, created_by, created_at, "
                "updated_at) VALUES (:id, :agent_id, 1, NULL, CAST(:spec AS jsonb), :hash, "
                "'active', 'migration', '[]'::jsonb, :workspace_id, :created_by, :now, :now)"
            ),
            {
                "id": revision_id,
                "agent_id": row.id,
                "spec": json.dumps(spec),
                "hash": _config_hash(spec),
                "workspace_id": row.workspace_id,
                "created_by": row.created_by,
                "now": now,
            },
        )
        bind.execute(
            sa.text("UPDATE agents SET current_revision_id = :rid WHERE id = :aid"),
            {"rid": revision_id, "aid": row.id},
        )


def upgrade() -> None:
    op.create_table(
        "agent_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("parent_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("spec", postgresql.JSONB(), nullable=False),
        sa.Column("config_hash", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column(
            "evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("agent_id", "number", name="uq_agent_revisions_number"),
    )
    op.create_index("ix_agent_revisions_agent_id", "agent_revisions", ["agent_id"])
    op.create_index("ix_agent_revisions_workspace_id", "agent_revisions", ["workspace_id"])
    op.create_index("ix_agent_revisions_created_by", "agent_revisions", ["created_by"])

    op.add_column(
        "agents", sa.Column("current_revision_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    _backfill()

    op.create_table(
        "agent_experiments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "control_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("weights", postgresql.JSONB(), nullable=False),
        sa.Column("policy", postgresql.JSONB(), nullable=False),
        sa.Column(
            "decisions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stop_reason", sa.String(32), nullable=True),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_agent_experiments_agent_id", "agent_experiments", ["agent_id"])
    op.create_index("ix_agent_experiments_workspace_id", "agent_experiments", ["workspace_id"])
    op.create_index("ix_agent_experiments_created_by", "agent_experiments", ["created_by"])
    op.create_index(
        "uq_agent_experiments_running",
        "agent_experiments",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )

    op.add_column(
        "tasks",
        sa.Column(
            "agent_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_revisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "experiment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_experiments.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_tasks_agent_revision_id", "tasks", ["agent_revision_id"])
    op.create_index("ix_tasks_experiment_id", "tasks", ["experiment_id"])


def downgrade() -> None:
    op.drop_index("ix_tasks_experiment_id", table_name="tasks")
    op.drop_index("ix_tasks_agent_revision_id", table_name="tasks")
    op.drop_column("tasks", "experiment_id")
    op.drop_column("tasks", "agent_revision_id")
    op.drop_table("agent_experiments")
    op.drop_column("agents", "current_revision_id")
    op.drop_table("agent_revisions")
