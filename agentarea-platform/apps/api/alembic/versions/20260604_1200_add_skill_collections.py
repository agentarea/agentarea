"""Add skill_collections table and collection_skills association table

Revision ID: 20260604_1200_add_skill_collections
Revises: tt1_merge_heads
Create Date: 2026-06-04 12:00:00.000000

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260604_1200_add_skill_collections"
down_revision: str = "tt1_merge_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create skill_collections and collection_skills tables."""
    # ========================================
    # SKILL_COLLECTIONS TABLE
    # ========================================
    op.create_table(
        "skill_collections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
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
        sa.UniqueConstraint(
            "workspace_id", "slug", name="uq_skill_collections_workspace_slug"
        ),
    )

    op.create_index("ix_skill_collections_workspace_id", "skill_collections", ["workspace_id"])
    op.create_index("ix_skill_collections_created_by", "skill_collections", ["created_by"])
    op.create_index("ix_skill_collections_slug", "skill_collections", ["slug"])

    # ========================================
    # COLLECTION_SKILLS ASSOCIATION TABLE
    # ========================================
    op.create_table(
        "collection_skills",
        sa.Column(
            "collection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skill_collections.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "skill_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_index(
        "ix_collection_skills_collection_id", "collection_skills", ["collection_id"]
    )
    op.create_index("ix_collection_skills_skill_id", "collection_skills", ["skill_id"])


def downgrade() -> None:
    """Drop collection_skills and skill_collections tables."""
    op.drop_index("ix_collection_skills_skill_id", table_name="collection_skills")
    op.drop_index("ix_collection_skills_collection_id", table_name="collection_skills")
    op.drop_table("collection_skills")

    op.drop_index("ix_skill_collections_slug", table_name="skill_collections")
    op.drop_index("ix_skill_collections_created_by", table_name="skill_collections")
    op.drop_index("ix_skill_collections_workspace_id", table_name="skill_collections")
    op.drop_table("skill_collections")
