"""Store immutable raw resource usage independently of billing.

Revision ID: 20260918_1200_resource_usage
Revises: 20260917_1100_exec_fired_by
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260918_1200_resource_usage"
down_revision: str | None = "20260917_1100_exec_fired_by"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Deliberately no foreign keys: workspace and runtime deletion must not erase
    # the original observations or prevent late deliveries from being retained.
    op.create_table(
        "resource_usage_events",
        sa.Column("sequence", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.SmallInteger(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("resource_kind", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=False),
        sa.Column("incarnation_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        # PostgreSQL timestamps stop at microseconds; keep the source precision.
        sa.Column("occurred_at_source", sa.Text(), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("source", "event_id", name="uq_resource_usage_events_identity"),
        sa.CheckConstraint(
            "workspace_id <> '' OR resource_kind = 'platform_runtime'",
            name="ck_resource_usage_events_workspace",
        ),
        sa.CheckConstraint("jsonb_typeof(data) = 'object'", name="ck_resource_usage_events_data"),
    )
    op.create_index(
        "ix_resource_usage_events_workspace_sequence",
        "resource_usage_events",
        ["workspace_id", "sequence"],
    )
    op.create_index(
        "ix_resource_usage_events_workspace_occurred",
        "resource_usage_events",
        ["workspace_id", "occurred_at"],
    )
    op.create_index(
        "ix_resource_usage_storage_scope",
        "resource_usage_events",
        [
            sa.text("(data ->> 'storage_namespace')"),
            "workspace_id",
            "task_id",
            "resource_kind",
            sa.text("sequence DESC"),
        ],
        postgresql_where=sa.text(
            "kind IN ('storage.sample','storage.artifact.published') "
            "AND source IN ('storage-inventory','artifact-store')"
        ),
    )
    op.execute(
        """
        CREATE FUNCTION resource_usage_events_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'resource_usage_events is append-only; % is not permitted', TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER resource_usage_events_append_only
        BEFORE UPDATE OR DELETE ON resource_usage_events
        FOR EACH STATEMENT EXECUTE FUNCTION resource_usage_events_reject_mutation();
        """
    )


def downgrade() -> None:
    op.drop_table("resource_usage_events")
    op.execute("DROP FUNCTION resource_usage_events_reject_mutation()")
