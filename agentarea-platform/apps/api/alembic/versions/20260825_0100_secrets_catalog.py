"""Turn encrypted_secrets into a catalog and add the reference index

The table was a value store: `(workspace_id, secret_name)` to ciphertext, with
the name synthesised from whatever owned the secret. It becomes the catalog
itself — same table, same rows, extra columns — because a separate metadata
table would link to this one by natural key, leaving rename and delete to keep
two rows in step.

`owner_type`/`owner_id` are backfilled by parsing the names the eight platform
producers mint. Two kinds of name do not parse, and they are not the same:

- one carrying a producer's prefix that this module cannot read means a producer
  nobody told the parser about, and calling it user-owned would hand a user edit
  rights over a credential some connection resolves. That stops the migration.
- one carrying no producer prefix at all is a user's own secret. The agent-facing
  toolset has always accepted an arbitrary name, so these exist in the wild; a
  null owner is exactly right for them.

The distinction matters because this runs unattended as a Kubernetes Job on
every deploy: raising rolls the whole migration back while the new API rolls out
against the old schema, which breaks every secret write, not just this feature.

Revision ID: 20260825_0100_secrets_catalog
Revises: 20260804_0100_drop_last_used
Create Date: 2026-08-25 01:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from agentarea_secrets.naming import has_reserved_prefix, parse_managed_name
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260825_0100_secrets_catalog"
down_revision: str | None = "20260804_0100_drop_last_used"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("encrypted_secrets", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("encrypted_secrets", sa.Column("owner_type", sa.String(64), nullable=True))
    op.add_column("encrypted_secrets", sa.Column("owner_id", sa.String(255), nullable=True))
    op.add_column("encrypted_secrets", sa.Column("external_ref", sa.String(512), nullable=True))
    op.add_column(
        "encrypted_secrets",
        sa.Column("provider_binding_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    _backfill_ownership()

    # Only now can the column be nullable: until every row is classified, a null
    # value and a null ciphertext are indistinguishable states to reason about.
    op.alter_column("encrypted_secrets", "encrypted_value", nullable=True)

    # NOT VALID skips the table scan under ACCESS EXCLUSIVE; VALIDATE then takes
    # only a SHARE UPDATE EXCLUSIVE lock, which readers and writers survive.
    op.execute(
        """
        ALTER TABLE encrypted_secrets
        ADD CONSTRAINT ck_encrypted_secrets_value_or_ref
        CHECK (num_nonnulls(encrypted_value, external_ref) = 1) NOT VALID
        """
    )
    op.execute(
        "ALTER TABLE encrypted_secrets VALIDATE CONSTRAINT ck_encrypted_secrets_value_or_ref"
    )

    # The secrets list shows user-owned rows, and managed ones outnumber them:
    # every submitted task input field mints one.
    op.create_index(
        "ix_encrypted_secrets_user_owned",
        "encrypted_secrets",
        ["workspace_id"],
        postgresql_where=sa.text("owner_type IS NULL"),
    )

    op.create_table(
        "secret_references",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("secret_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("consumer_type", sa.String(64), nullable=False),
        sa.Column("consumer_id", sa.String(255), nullable=False),
        sa.Column("field", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        # RESTRICT is the delete guard itself. Consumers that keep their
        # reference inside a JSON document have no column to hang a foreign key
        # on; this row is where the database gets to refuse on their behalf.
        sa.ForeignKeyConstraint(["secret_id"], ["encrypted_secrets.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "secret_id",
            "consumer_type",
            "consumer_id",
            "field",
            name="uq_secret_references_consumer_slot",
        ),
    )
    op.create_index("ix_secret_references_workspace_id", "secret_references", ["workspace_id"])
    op.create_index("ix_secret_references_secret_id", "secret_references", ["secret_id"])


def _backfill_ownership() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, secret_name FROM encrypted_secrets")).fetchall()

    unparseable: list[str] = []
    for row in rows:
        owner = parse_managed_name(row.secret_name)
        if owner is None:
            if has_reserved_prefix(row.secret_name):
                # Claims a producer's prefix but does not parse: a producer this
                # module does not know about. Calling it user-owned would hand a
                # user edit rights over a credential some connection resolves.
                unparseable.append(row.secret_name)
            # Otherwise it is a user's own secret. The agent-facing toolset has
            # always accepted an arbitrary name, so these exist in the wild and
            # a null owner is exactly right for them.
            continue
        connection.execute(
            sa.text(
                "UPDATE encrypted_secrets SET owner_type = :owner_type, owner_id = :owner_id "
                "WHERE id = :id"
            ),
            {"owner_type": owner.owner_type, "owner_id": owner.owner_id, "id": row.id},
        )

    if unparseable:
        # This migration runs unattended as a Kubernetes Job on every deploy, so
        # raising here rolls the whole thing back while the new API rolls out
        # against the old schema. That is the right trade only for the case
        # above, where continuing would silently expose someone's credential.
        sample = ", ".join(sorted(unparseable)[:5])
        raise RuntimeError(
            f"{len(unparseable)} secret name(s) use a reserved producer prefix but do not "
            f"parse into an owner: {sample}. Teach agentarea_secrets.naming about that "
            "producer before migrating."
        )


def downgrade() -> None:
    op.drop_index("ix_secret_references_secret_id", table_name="secret_references")
    op.drop_index("ix_secret_references_workspace_id", table_name="secret_references")
    op.drop_table("secret_references")

    op.drop_index("ix_encrypted_secrets_user_owned", table_name="encrypted_secrets")
    op.execute("ALTER TABLE encrypted_secrets DROP CONSTRAINT ck_encrypted_secrets_value_or_ref")

    # Rows backed by an external provider hold no ciphertext, so there is nothing
    # for the pre-catalog schema to store. Refuse rather than drop credentials.
    external = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM encrypted_secrets WHERE external_ref IS NOT NULL"))
        .scalar_one()
    )
    if external:
        raise RuntimeError(
            f"{external} secret(s) are backed by an external provider and hold no value in "
            "this database. Migrate them back to the database backend before downgrading."
        )
    op.alter_column("encrypted_secrets", "encrypted_value", nullable=False)

    op.drop_column("encrypted_secrets", "provider_binding_id")
    op.drop_column("encrypted_secrets", "external_ref")
    op.drop_column("encrypted_secrets", "owner_id")
    op.drop_column("encrypted_secrets", "owner_type")
    op.drop_column("encrypted_secrets", "description")
