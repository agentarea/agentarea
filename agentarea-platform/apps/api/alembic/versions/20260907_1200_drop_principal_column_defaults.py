"""Drop the 'system'/'default' column defaults on principal and tenant columns.

Every workspace-scoped table was created with ``created_by`` defaulting to the
string ``'system'`` and ``workspace_id`` defaulting to ``'default'``. Those are
the same silent fallbacks that were just removed from the application layer,
one level lower: an INSERT that forgets either column does not fail, it lands a
row owned by a principal nobody can authenticate as, in a tenant nobody owns.
Both columns stay NOT NULL, so after this the omission is an error.

The defaults are discovered from ``information_schema`` rather than listed, so
this covers every table that has them without tracking which migration created
which. Existing rows are untouched — this changes what a future INSERT may omit,
not what is already stored.

Revision ID: 20260907_1200_drop_defaults
Revises: 20260908_1000_multi_catalog_conn
"""

from alembic import op
from sqlalchemy import text

revision = "20260907_1200_drop_defaults"
down_revision = "20260908_1000_multi_catalog_conn"
branch_labels = None
depends_on = None


_PRINCIPAL_COLUMNS = ("created_by", "workspace_id")


def upgrade() -> None:
    conn = op.get_bind()
    # Only the two sentinel literals, so a column with some other, deliberate
    # default is left alone. Postgres renders these as ``'system'::varchar``.
    rows = conn.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() "
            "AND column_name = ANY(:columns) "
            "AND (column_default LIKE '''system''%' OR column_default LIKE '''default''%')"
        ),
        {"columns": list(_PRINCIPAL_COLUMNS)},
    ).fetchall()

    for table_name, column_name in rows:
        op.execute(f'ALTER TABLE "{table_name}" ALTER COLUMN "{column_name}" DROP DEFAULT')


def downgrade() -> None:
    """Deliberately not restored.

    Re-adding the defaults would reinstate exactly the fallback this removes,
    and the original values ('system' / 'default') identify no real principal or
    tenant, so there is nothing to roll back to that is worth having.
    """
