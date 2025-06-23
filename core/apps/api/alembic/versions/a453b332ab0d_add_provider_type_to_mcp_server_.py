"""add json_spec and description, rename server_id to server_spec_id.

Revision ID: a453b332ab0d
Revises: c6d7e8f9a0b1
Create Date: 2024-12-19 12:00:00.000000

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "a453b332ab0d"
down_revision = "c6d7e8f9a0b1"  # Point to latest migration
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add description column
    op.add_column("mcp_server_instances", sa.Column("description", sa.Text(), nullable=True))

    # Add json_spec column to replace config and endpoint_url
    op.add_column(
        "mcp_server_instances",
        sa.Column("json_spec", sa.JSON(), nullable=False, server_default="{}"),
    )

    # Drop foreign key constraint first
    op.drop_constraint(
        "mcp_server_instances_server_id_fkey", "mcp_server_instances", type_="foreignkey"
    )

    # Rename server_id to server_spec_id and change type to String, make nullable
    op.alter_column(
        "mcp_server_instances",
        "server_id",
        new_column_name="server_spec_id",
        existing_type=postgresql.UUID(),
        type_=sa.String(255),
        nullable=True,
    )

    # Migrate existing data from config to json_spec
    op.execute("""
        UPDATE mcp_server_instances
        SET json_spec = COALESCE(config::jsonb, '{}'::jsonb)
    """)

    # Add endpoint_url from old column to json_spec if it exists
    op.execute("""
        UPDATE mcp_server_instances
        SET json_spec = json_spec::jsonb || jsonb_build_object('endpoint_url', endpoint_url)
        WHERE endpoint_url IS NOT NULL
    """)

    # Drop old columns
    op.drop_column("mcp_server_instances", "config")
    op.drop_column("mcp_server_instances", "endpoint_url")


def downgrade() -> None:
    # Add back old columns
    op.add_column("mcp_server_instances", sa.Column("endpoint_url", sa.String(), nullable=True))
    op.add_column(
        "mcp_server_instances", sa.Column("config", sa.JSON(), nullable=False, server_default="{}")
    )

    # Migrate data back from json_spec
    op.execute("""
        UPDATE mcp_server_instances
        SET config = json_spec,
            endpoint_url = json_spec->>'endpoint_url'
    """)

    # Revert server_spec_id back to server_id
    op.alter_column(
        "mcp_server_instances",
        "server_spec_id",
        new_column_name="server_id",
        existing_type=sa.String(255),
        type_=postgresql.UUID(),
        nullable=False,
    )

    # Recreate foreign key constraint
    op.create_foreign_key(
        "mcp_server_instances_server_id_fkey",
        "mcp_server_instances",
        "mcp_servers",
        ["server_id"],
        ["id"],
    )

    # Drop new columns
    op.drop_column("mcp_server_instances", "json_spec")
    op.drop_column("mcp_server_instances", "description")
