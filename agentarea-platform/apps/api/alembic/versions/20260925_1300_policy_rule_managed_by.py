"""A policy rule records which automation owns it

The agent editor's approval toggle reconciled every APPROVAL rule on the agent,
so a member editing the agent's tools deleted approval rules a workspace admin
had authored through the policy service. The toggle now marks the rules it
writes (``managed_by = 'agent_tools'``) and only ever changes those.

Existing rows stay unmarked, which treats them as authored: which of them the
toggle once wrote cannot be told apart from an admin's, and leaving an approval
in place is recoverable where deleting one is not. An admin removes them from
Policies.

Revision ID: 20260925_1300_policy_managed_by
Revises: 20260925_1200_model_specs_ws_uq
Create Date: 2026-09-25 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_1300_policy_managed_by"
down_revision: str | None = "20260925_1200_model_specs_ws_uq"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("policies", sa.Column("managed_by", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("policies", "managed_by")
