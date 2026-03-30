"""Replace compound_skills/compound_skill_members with self-referential skill_members

Revision ID: 008_add_skill_members_table
Revises: 007_add_api_keys
Create Date: 2026-03-03 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "008_add_skill_members_table"
down_revision: str = "007_add_api_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the old compound_skill_members and compound_skills tables
    # (compound_skills were never deployed to production; safe to drop)
    op.drop_index("ix_compound_skill_members_skill_id", table_name="compound_skill_members")
    op.drop_index("ix_compound_skill_members_compound_id", table_name="compound_skill_members")
    op.drop_table("compound_skill_members")

    op.drop_index("ix_compound_skills_workspace_id", table_name="compound_skills")
    op.drop_table("compound_skills")

    # Create self-referential skill_members table
    op.create_table(
        "skill_members",
        sa.Column(
            "parent_skill_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "child_skill_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default="true"),
        # List of child_skill_id strings that must run before this child
        sa.Column(
            "dependencies",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    op.create_primary_key(
        "pk_skill_members", "skill_members", ["parent_skill_id", "child_skill_id"]
    )
    op.create_index("ix_skill_members_parent_skill_id", "skill_members", ["parent_skill_id"])
    op.create_index("ix_skill_members_child_skill_id", "skill_members", ["child_skill_id"])


def downgrade() -> None:
    op.drop_index("ix_skill_members_child_skill_id", table_name="skill_members")
    op.drop_index("ix_skill_members_parent_skill_id", table_name="skill_members")
    op.drop_table("skill_members")

    # Restore compound_skills
    op.create_table(
        "compound_skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.String(50), nullable=False, server_default="1.0.0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_compound_skills_workspace_id", "compound_skills", ["workspace_id"])

    # Restore compound_skill_members
    op.create_table(
        "compound_skill_members",
        sa.Column(
            "compound_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("compound_skills.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "skill_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "dependencies",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_primary_key(
        "pk_compound_skill_members", "compound_skill_members", ["compound_id", "skill_id"]
    )
    op.create_index(
        "ix_compound_skill_members_compound_id", "compound_skill_members", ["compound_id"]
    )
    op.create_index("ix_compound_skill_members_skill_id", "compound_skill_members", ["skill_id"])
