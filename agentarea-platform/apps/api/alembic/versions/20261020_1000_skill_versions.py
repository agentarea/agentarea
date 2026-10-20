"""skill_versions: every package a skill pointed at, for history and rollback (ADR-0044)

A workspace's own skill bodies become immutable packages keyed by digest under
``skills/<workspace>/packages/<digest>/``; an edit stores a new one and moves the
skill's pointer. Each move is a row here. Existing skills get their current
package as their first version; one still at its mutable pre-package copy
(``skills/<workspace>/<id>/``) gets it when it is moved, on its next read or by
``agentarea-api skills move-own-copies-to-packages``.

Revision ID: 20261020_1000_skill_versions
Revises: 20261019_2200_event_counts
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261020_1000_skill_versions"
down_revision: str | None = "20261019_2200_event_counts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skill_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "skill_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("s3_path", sa.String(1024), nullable=False),
        sa.Column("digest", sa.String(64), nullable=True),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("catalog_version", sa.String(100), nullable=True),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_skill_versions_skill_created", "skill_versions", ["skill_id", "created_at"])
    op.create_index("ix_skill_versions_workspace_id", "skill_versions", ["workspace_id"])
    op.create_index("ix_skill_versions_created_by", "skill_versions", ["created_by"])
    op.execute(BACKFILL)


# A skill already on an immutable package starts its history there; the digest
# is the package's last path segment. Run by the test of this migration too.
BACKFILL = """
        INSERT INTO skill_versions (id, skill_id, s3_path, digest, reason, catalog_version,
                                    workspace_id, created_by, created_at, updated_at)
        SELECT gen_random_uuid(), s.id, s.s3_path,
               split_part(rtrim(s.s3_path, '/'), '/', -1),
               CASE WHEN s.registry_item_id IS NULL THEN 'create' ELSE 'install' END,
               CASE WHEN split_part(s.s3_path, '/', 2) = 'catalog'
                      OR split_part(s.s3_path, '/', 3) = 'catalog'
                    THEN rii.installed_version END,
               s.workspace_id, s.created_by, s.updated_at, s.updated_at
        FROM skills s
        LEFT JOIN registry_item_installs rii
          ON rii.registry_item_id = s.registry_item_id AND rii.workspace_id = s.workspace_id
        WHERE s.s3_path LIKE 'skills/%'
          AND (split_part(s.s3_path, '/', 2) = 'catalog'
               OR split_part(s.s3_path, '/', 3) IN ('catalog', 'packages'))
          AND NOT EXISTS (SELECT 1 FROM skill_versions v WHERE v.skill_id = s.id)
"""


def downgrade() -> None:
    op.drop_index("ix_skill_versions_created_by", table_name="skill_versions")
    op.drop_index("ix_skill_versions_workspace_id", table_name="skill_versions")
    op.drop_index("ix_skill_versions_skill_created", table_name="skill_versions")
    op.drop_table("skill_versions")
