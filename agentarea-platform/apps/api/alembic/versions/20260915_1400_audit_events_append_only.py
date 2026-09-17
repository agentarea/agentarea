"""Enforce append-only writes on audit_events.

The table has always documented itself as append-only, but nothing enforced
it: the application role could update or delete its own audit trail, which is
the first property an auditor asks us to demonstrate.

A trigger is used rather than a plain ``REVOKE`` because no deployment we ship
would be bound by one. Production connects as the CloudNativePG app role,
which owns the table and can therefore re-grant itself any privilege it
revoked; local compose and CI connect as ``postgres``, a superuser, which
bypasses privilege checks outright. The trigger holds in both.

TRUNCATE is deliberately still permitted: it fires a different trigger event,
it is what local and test teardown uses, and wiping the whole table is a loud
act rather than a way to quietly edit one entry. Restricting it belongs with
the production role split, not here.

Revision ID: 20260915_1400_audit_append_only
Revises: 20260915_1200_drop_tasks_uid
Create Date: 2026-09-15 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260915_1400_audit_append_only"
down_revision: str | None = "20260915_1200_drop_tasks_uid"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_events_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only; % is not permitted', TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    # Statement-level: the statement is refused whether or not it matches rows,
    # so a blanket "UPDATE audit_events SET ..." cannot pass by matching none.
    op.execute(
        """
        CREATE TRIGGER audit_events_append_only
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH STATEMENT EXECUTE FUNCTION audit_events_reject_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events;")
    op.execute("DROP FUNCTION IF EXISTS audit_events_reject_mutation();")
