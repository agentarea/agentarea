"""Rename tools_config to tools in agents table

Revision ID: 004_rename_tools_config_to_tools
Revises: 003_add_encrypted_secrets_table
Create Date: 2026-01-10 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004_rename_tools_config_to_tools"
down_revision: str | None = "003_add_encrypted_secrets_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Rename tools_config column to tools in agents table."""
    op.alter_column("agents", "tools_config", new_column_name="tools")


def downgrade() -> None:
    """Rename tools column back to tools_config in agents table."""
    op.alter_column("agents", "tools", new_column_name="tools_config")
