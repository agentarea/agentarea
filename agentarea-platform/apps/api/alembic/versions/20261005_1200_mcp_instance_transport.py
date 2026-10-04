"""MCP instance transport is a column, not a key in json_spec

An instance's transport (url, docker, command, bundle) was an optional ``type``
key in ``json_spec`` (or the older ``server_type``), and every reader that
found it missing derived one from the server spec with its own default. The
column is now the one place it is recorded.

Each row gets the transport it actually ran with. A bundle, a package-converted
docker instance (its own ``image``) and an instance typed ``url`` keep theirs:
the API dialled those as such. Every other row was started by the Go gateway,
which read the server's ``remote_url``, then ``cmd``, then the ``type`` of the
instance spec laid over the server spec, then ``docker_image_url``; the
backfill follows the same order. A row none of these resolve has no transport
anywhere; the upgrade names those rows and stops rather than guess one.

Revision ID: 20261005_1200_mcp_inst_transport
Revises: 20261001_1800_client_toolsets
Create Date: 2026-10-05 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261005_1200_mcp_inst_transport"
down_revision: str | None = "20261001_1800_client_toolsets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TRANSPORT_CHECK = "transport IN ('url', 'docker', 'command', 'bundle')"


def upgrade() -> None:
    op.add_column("mcp_server_instances", sa.Column("transport", sa.String(16), nullable=True))
    op.execute(
        """
        UPDATE mcp_server_instances i
        SET transport = CASE
            WHEN i.json_spec->>'type' = 'bundle' THEN 'bundle'
            WHEN i.json_spec->>'type' = 'docker' AND NULLIF(i.json_spec->>'image', '') IS NOT NULL
                THEN 'docker'
            WHEN COALESCE(i.json_spec->>'type', i.json_spec->>'server_type') = 'url' THEN 'url'
            WHEN NULLIF(s.remote_url, '') IS NOT NULL THEN 'url'
            WHEN s.cmd IS NOT NULL AND s.cmd::jsonb NOT IN ('null'::jsonb, '[]'::jsonb)
                THEN 'command'
            WHEN COALESCE(i.json_spec->>'type', i.json_spec->>'server_type') IN ('docker', 'command')
                THEN COALESCE(i.json_spec->>'type', i.json_spec->>'server_type')
            WHEN s.json_spec->>'type' IN ('url', 'docker', 'command') THEN s.json_spec->>'type'
            WHEN NULLIF(s.docker_image_url, '') IS NOT NULL THEN 'docker'
        END
        FROM mcp_server_instances i2
        LEFT JOIN mcp_servers s ON s.id::text = i2.server_spec_id
        WHERE i2.id = i.id
        """
    )
    unresolved = (
        op.get_bind()
        .execute(sa.text("SELECT id::text FROM mcp_server_instances WHERE transport IS NULL"))
        .scalars()
        .all()
    )
    if unresolved:
        raise RuntimeError(
            "MCP instances with no transport in their own json_spec or their server spec: "
            + ", ".join(sorted(unresolved))
        )
    op.alter_column("mcp_server_instances", "transport", nullable=False)
    op.create_check_constraint(
        "ck_mcp_server_instances_transport",
        "mcp_server_instances",
        _TRANSPORT_CHECK,
    )
    op.execute(
        "UPDATE mcp_server_instances SET json_spec = json_spec - 'type' - 'server_type' "
        "WHERE json_spec ? 'type' OR json_spec ? 'server_type'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE mcp_server_instances "
        "SET json_spec = json_spec || jsonb_build_object('type', transport)"
    )
    op.drop_constraint("ck_mcp_server_instances_transport", "mcp_server_instances", type_="check")
    op.drop_column("mcp_server_instances", "transport")
