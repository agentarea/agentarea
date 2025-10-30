"""Add encrypted secrets table for database secret manager

Revision ID: 003_add_encrypted_secrets_table
Revises: 002_add_task_events_timestamps
Create Date: 2025-01-10 12:00:00.000000

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "003_add_encrypted_secrets_table"
down_revision: str | None = "002_add_task_events_timestamps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create encrypted_secrets table for database-backed secret storage."""
    op.create_table(
        "encrypted_secrets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("secret_name", sa.String(255), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        # Audit fields
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        # Constraints
        sa.UniqueConstraint(
            "workspace_id", "secret_name", name="uq_encrypted_secrets_workspace_name"
        ),
    )

    # Index for fast lookups by workspace and secret name
    op.create_index(
        "idx_encrypted_secrets_workspace_name",
        "encrypted_secrets",
        ["workspace_id", "secret_name"],
    )


def downgrade() -> None:
    """Drop encrypted_secrets table."""
    op.drop_index("idx_encrypted_secrets_workspace_name", table_name="encrypted_secrets")
    op.drop_table("encrypted_secrets")
