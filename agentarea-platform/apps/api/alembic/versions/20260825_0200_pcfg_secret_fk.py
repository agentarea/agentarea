"""Point provider_configs at its API key secret by id as well as by name

`api_key` holds the *name* of the secret carrying the key, and resolution keeps
going through it — the worker's execution activities read it on the hot path and
this migration deliberately leaves that alone. What a name cannot do is stop the
secret being deleted out from under the config, or let the catalog list the
configs using a secret without parsing names back into ids. The foreign key
does both.

Revision ID: 20260825_0200_pcfg_secret_fk
Revises: 20260825_0100_secrets_catalog
Create Date: 2026-08-25 02:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260825_0200_pcfg_secret_fk"
down_revision: str | None = "20260825_0100_secrets_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "provider_configs",
        sa.Column("api_key_secret_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # Match on name within the same workspace. Names are unique per workspace,
    # not globally, so the workspace predicate is what keeps a config from
    # adopting an identically named secret belonging to another tenant.
    op.execute(
        """
        UPDATE provider_configs pc
        SET api_key_secret_id = es.id
        FROM encrypted_secrets es
        WHERE pc.api_key IS NOT NULL
          AND es.secret_name = pc.api_key
          AND es.workspace_id = pc.workspace_id
        """
    )

    # A config naming a secret that does not exist already resolves to nothing
    # at runtime; the foreign key just declines to invent a row for it. Left
    # null, and the pre-existing breakage stays visible rather than blocking
    # the migration.
    op.create_foreign_key(
        "fk_provider_configs_api_key_secret",
        "provider_configs",
        "encrypted_secrets",
        ["api_key_secret_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_provider_configs_api_key_secret_id",
        "provider_configs",
        ["api_key_secret_id"],
    )

    # The foreign key alone refuses the delete but says nothing about who is
    # holding the secret. Without a matching reverse-index row, an existing
    # config is invisible to the catalog: the secrets list shows the key as
    # unused, and deleting it returns a 409 whose "used_by" is empty — refused,
    # with no way to find out by whom. Only borrowed secrets need one; a config
    # that minted its own is its owner, not a consumer of someone else's.
    op.execute(
        """
        INSERT INTO secret_references
            (id, workspace_id, secret_id, consumer_type, consumer_id, field,
             created_at, updated_at)
        SELECT gen_random_uuid(), pc.workspace_id, pc.api_key_secret_id,
               'provider_config', pc.id::text, 'api_key', now(), now()
        FROM provider_configs pc
        JOIN encrypted_secrets es ON es.id = pc.api_key_secret_id
        WHERE pc.api_key_secret_id IS NOT NULL
          AND es.owner_type IS NULL
        ON CONFLICT ON CONSTRAINT uq_secret_references_consumer_slot DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM secret_references WHERE consumer_type = 'provider_config'")
    op.drop_index("ix_provider_configs_api_key_secret_id", table_name="provider_configs")
    op.drop_constraint("fk_provider_configs_api_key_secret", "provider_configs", type_="foreignkey")
    op.drop_column("provider_configs", "api_key_secret_id")
