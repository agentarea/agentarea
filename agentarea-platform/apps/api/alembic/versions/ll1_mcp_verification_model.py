"""mcp verification model — drop status, add verification/last_dispatch/tools

Revision ID: ll1_mcp_verification_model
Revises: kk1_json_spec_registry_url
Create Date: 2026-04-18

"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB

logger = logging.getLogger(__name__)

revision: str = "ll1_mcp_verification_model"
down_revision: str = "kk1_json_spec_registry_url"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEVER_ATTEMPTED = '{"schema_version":1,"status":"never_attempted","at":null,"error":null}'


def upgrade() -> None:
    op.add_column(
        "mcp_server_instances",
        sa.Column(
            "verification",
            JSONB,
            nullable=False,
            server_default=_NEVER_ATTEMPTED,
        ),
    )
    op.add_column(
        "mcp_server_instances",
        sa.Column("last_dispatch", JSONB, nullable=True),
    )
    op.add_column(
        "mcp_server_instances",
        sa.Column("tools", JSONB, nullable=True),
    )

    # Use json_build_object to avoid SQLAlchemy named-param colon stripping in --sql mode.
    op.execute(
        sa.text(
            "UPDATE mcp_server_instances"
            " SET verification = json_build_object("
            "   'schema_version', 1,"
            "   'status', 'never_attempted',"
            "   'at', NULL,"
            "   'error', NULL"
            ")"
        )
    )

    op.drop_column("mcp_server_instances", "status")


def downgrade() -> None:
    logger.warning(
        "Migration downgrade is lossy — last_dispatch and tool caches are not recoverable."
    )

    op.add_column(
        "mcp_server_instances",
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
    )

    op.execute(
        """
        UPDATE mcp_server_instances
        SET status = CASE
            WHEN verification->>'status' = 'succeeded' THEN 'connected'
            WHEN verification->>'status' = 'failed'    THEN 'failed'
            ELSE 'pending'
        END
        """
    )

    op.drop_column("mcp_server_instances", "tools")
    op.drop_column("mcp_server_instances", "last_dispatch")
    op.drop_column("mcp_server_instances", "verification")
