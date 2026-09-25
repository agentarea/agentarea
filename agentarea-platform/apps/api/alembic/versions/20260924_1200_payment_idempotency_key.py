"""At most one settled payment per paid request of a tool call

Paid tools pay inside a retryable activity. A retry after a successful payment
paid again, and nothing in ``payment_records`` could tell the two apart. Each
record now carries the idempotency key of the paid request (task + tool call +
position within the call), and only one completed record may hold a key.
Failed attempts stay as history, so the uniqueness is limited to completed rows.

Existing rows predate the key and each one is a payment that really happened,
including any double charge this bug already caused, so none is merged or
dropped: every row gets a key of its own (``legacy:<id>``) and the index cannot
fail to build on them.

Revision ID: 20260924_1200_payment_idem_key
Revises: 20260924_1000_allowed_tools_none
Create Date: 2026-09-24 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_1200_payment_idem_key"
down_revision: str | None = "20260924_1000_allowed_tools_none"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_payment_records_settled_idempotency_key"


def upgrade() -> None:
    op.add_column("payment_records", sa.Column("idempotency_key", sa.String(), nullable=True))
    op.execute("UPDATE payment_records SET idempotency_key = 'legacy:' || id::text")
    op.alter_column("payment_records", "idempotency_key", nullable=False)
    op.create_index(
        _INDEX,
        "payment_records",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("status = 'completed'"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="payment_records")
    op.drop_column("payment_records", "idempotency_key")
