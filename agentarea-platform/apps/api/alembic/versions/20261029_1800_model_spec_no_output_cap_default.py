"""model_specs.max_output_tokens: no column default, and the defaulted gateway rows cleared

hh1_enrich_model_specs gave the column server_default 4096. Anything that inserted
a spec without naming the column got a 4096-token cap it never asked for: the
operator creates the AgentArea gateway's models that way, so every reply of every
one of them stopped at 4096 tokens while the model and the gateway allowed more.

The default goes, so an unstated cap stays unknown (NULL) and only the policy's
per-call ceiling applies. The AgentArea rows holding exactly 4096 got it from the
default, since the operator never wrote the column; they are cleared. Other rows
keep their value: catalog and discovered specs name the cap explicitly.

Revision ID: 20261029_1800_output_cap
Revises: 20261029_1200_provider_http
Create Date: 2026-10-29 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261029_1800_output_cap"
down_revision: str | None = "20261029_1200_provider_http"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("model_specs", "max_output_tokens", server_default=None)
    op.execute(
        sa.text(
            "UPDATE model_specs SET max_output_tokens = NULL "
            "FROM provider_specs "
            "WHERE provider_specs.id = model_specs.provider_spec_id "
            "AND provider_specs.provider_key = 'agentarea' "
            "AND model_specs.max_output_tokens = 4096"
        )
    )


def downgrade() -> None:
    op.alter_column("model_specs", "max_output_tokens", server_default="4096")
