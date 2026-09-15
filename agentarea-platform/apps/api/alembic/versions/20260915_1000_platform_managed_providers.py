"""Providers whose credentials the deployment supplies, and providers that need none.

Revision ID: 20260915_1000_platform_providers
Revises: 20260915_0900_merge_heads
Create Date: 2026-09-15 10:00:00.000000

Two independent facts the schema could not previously state.

``provider_configs.managed_by`` — who owns this configuration's credentials. Until
now every configuration was a tenant's own: someone pasted a key into it, and the
only thing that could run was what they had paid a provider for separately. An
operator that wants to supply the key itself (our hosted service; equally, a company
handing one corporate key to every internal workspace) had no way to say so, and no
way to stop the tenant editing or deleting the configuration underneath it.

``provider_specs.requires_api_key`` — whether this provider type needs a key at all.
Ollama, vLLM and any local or proxied endpoint do not, and the UI's unconditional
"API key required" warning was simply wrong for them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260915_1000_platform_providers"
down_revision: str | None = "20260915_0900_merge_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NULL, not a 'user' default.
    #
    # Every row that exists today is a tenant's own configuration, and NULL says
    # exactly that without claiming the operator made a decision about it. It also
    # keeps the column free of a value the old binary would have to know about:
    # migrations run before the new pods exist, so for the length of a rollout the
    # previous build is still inserting rows here, and it writes nothing to this
    # column. A row it creates mid-rollout is a tenant config, which is what NULL
    # means — whereas a NOT NULL DEFAULT 'platform' would have silently handed
    # those rows our credentials.
    op.add_column(
        "provider_configs",
        sa.Column("managed_by", sa.String(length=32), nullable=True),
    )

    # Partial index: the platform-managed rows are read on every model list, by
    # every workspace, and there are a handful of them among all tenant configs.
    op.create_index(
        "ix_provider_configs_managed_by",
        "provider_configs",
        ["managed_by"],
        unique=False,
        postgresql_where=sa.text("managed_by IS NOT NULL"),
    )

    # A provider is assumed to need a key, because all but the local ones do and
    # because the safe failure is asking for a key that turns out to be optional —
    # not omitting the field for a provider that rejects every call without one.
    op.add_column(
        "provider_specs",
        sa.Column(
            "requires_api_key",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )

    # Ollama serves local weights over an unauthenticated HTTP endpoint; there is no
    # key to ask for, and asking produced a warning the user could only silence by
    # inventing one.
    #
    # Deliberately just this one. The provider catalog carries 84 provider keys
    # (litellm's own list), and the rest either require a key or require one often
    # enough that guessing on their behalf is worse than an operator setting the
    # column. Matched on provider_key, so a deployment that never seeded Ollama is
    # simply unaffected.
    op.execute(
        """
        UPDATE provider_specs
        SET requires_api_key = false
        WHERE provider_key = 'ollama'
        """
    )


def downgrade() -> None:
    op.drop_column("provider_specs", "requires_api_key")
    op.drop_index("ix_provider_configs_managed_by", table_name="provider_configs")
    op.drop_column("provider_configs", "managed_by")
