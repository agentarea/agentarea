"""Add skills table and agent_skills association table

Revision ID: 005_add_skills_table
Revises: 004_rename_tools_config_to_tools
Create Date: 2026-02-04 12:00:00.000000

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "005_add_skills_table"
down_revision: str = "004_rename_tools_config_to_tools"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create skills table and agent_skills association table."""
    # ========================================
    # SKILLS TABLE
    # ========================================
    op.create_table(
        "skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "source_type",
            sa.String(50),
            nullable=False,
            server_default="content",
        ),  # content, zip, github, path
        sa.Column("source_url", sa.String(1024), nullable=True),  # GitHub URL or original source
        sa.Column("content", sa.Text(), nullable=True),  # Main skill markdown content
        sa.Column("s3_path", sa.String(1024), nullable=True),  # S3 path for multi-file packages
        # Workspace and audit fields
        sa.Column("workspace_id", sa.String(255), nullable=False, server_default="default"),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        # Timestamps
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    # Create indexes for common queries
    op.create_index("ix_skills_workspace_id", "skills", ["workspace_id"])
    op.create_index("ix_skills_name", "skills", ["name"])
    op.create_index("ix_skills_source_type", "skills", ["source_type"])

    # ========================================
    # AGENT_SKILLS ASSOCIATION TABLE
    # ========================================
    op.create_table(
        "agent_skills",
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "skill_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # Timestamps for when the association was created
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Create indexes for the association table
    op.create_index("ix_agent_skills_agent_id", "agent_skills", ["agent_id"])
    op.create_index("ix_agent_skills_skill_id", "agent_skills", ["skill_id"])


def downgrade() -> None:
    """Drop skills and agent_skills tables."""
    # Drop association table first (due to foreign key constraints)
    op.drop_index("ix_agent_skills_skill_id", table_name="agent_skills")
    op.drop_index("ix_agent_skills_agent_id", table_name="agent_skills")
    op.drop_table("agent_skills")

    # Drop skills table
    op.drop_index("ix_skills_source_type", table_name="skills")
    op.drop_index("ix_skills_name", table_name="skills")
    op.drop_index("ix_skills_workspace_id", table_name="skills")
    op.drop_table("skills")
