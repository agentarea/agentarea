"""drop projects.minio_prefix — derive prefix from project_id under ArtifactService

Revision ID: mm1_drop_project_minio_prefix
Revises: ll1_mcp_verification_model
Create Date: 2026-04-26

Project files now live in the artifacts bucket under
``workspaces/{workspace_id}/projects/{project_id}/...`` via ``ArtifactService``.
The prefix is fully derived from the project id, so storing it on the row
adds no information.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "mm1_drop_project_minio_prefix"
down_revision: str = "ll1_mcp_verification_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("projects", "minio_prefix")


def downgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "minio_prefix",
            sa.String(500),
            nullable=False,
            server_default="",
        ),
    )
    op.execute(
        sa.text(
            "UPDATE projects SET minio_prefix = 'projects/' || id::text || '/files/'"
        )
    )
    op.alter_column("projects", "minio_prefix", server_default=None)
