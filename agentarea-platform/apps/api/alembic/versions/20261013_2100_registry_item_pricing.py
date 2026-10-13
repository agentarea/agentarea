"""registry_items.pricing: whether using a connection costs money

The connections gallery filters on it beside protocol and hosting: "paid" when
the platform's key may pay for a call that costs something (billed through
AgentArea), "own_key" when the vendor bills the workspace's own account, "free"
otherwise (wiki ADR-0038). Derived by catalog_facets.derive_facets on every
sync; backfilled here from the curated metadata so the facet works before the
next sync.

Revision ID: 20261013_2100_item_pricing
Revises: 20261013_1800_agent_answer_check
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261013_2100_item_pricing"
down_revision: str | None = "20261013_1800_agent_answer_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("registry_items", sa.Column("pricing", sa.String(16), nullable=True))
    # Mirrors catalog_facets._pricing.
    op.execute(
        """
        UPDATE registry_items SET pricing = CASE
            WHEN NOT jsonb_path_exists(
                coalesce(spec #> '{raw_spec,metadata,agentarea:cost}', '{}'::jsonb),
                '$.default.source ? (@ == "rate" || @ == "reported" || @ == "settled")'
            ) AND NOT jsonb_path_exists(
                coalesce(spec #> '{raw_spec,metadata,agentarea:cost}', '{}'::jsonb),
                '$.tools.*.source ? (@ == "rate" || @ == "reported" || @ == "settled")'
            ) THEN 'free'
            WHEN coalesce(spec #> '{raw_spec,metadata,agentarea:payers}' ? 'platform', false)
                THEN 'paid'
            ELSE 'own_key'
        END
        WHERE registry_type = 'mcp_servers'
        """
    )
    op.drop_index("ix_registry_items_browse_facets", table_name="registry_items")
    op.create_index(
        "ix_registry_items_browse_facets",
        "registry_items",
        ["registry_type", "category"],
        postgresql_include=["protocol", "hosting", "pricing"],
        postgresql_where=sa.text("registry_active"),
    )


def downgrade() -> None:
    op.drop_index("ix_registry_items_browse_facets", table_name="registry_items")
    op.create_index(
        "ix_registry_items_browse_facets",
        "registry_items",
        ["registry_type", "category"],
        postgresql_include=["protocol", "hosting"],
        postgresql_where=sa.text("registry_active"),
    )
    op.drop_column("registry_items", "pricing")
