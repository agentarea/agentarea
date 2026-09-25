"""Model specs are unique per workspace, and each workspace prices its own

``uq_model_specs_provider_model`` was ``(provider_spec_id, model_name)`` across
every workspace. The first workspace to discover a model owned the only row for
it; every later workspace's discovery was handed that row, its model instances
pointed at it, and the first workspace's admin set the price the others were
billed and budgeted against. The key now includes ``workspace_id``.

Existing instances that point at another workspace's spec get a copy of that
spec in their own workspace and are repointed to it, so the price they run on
stops being someone else's to change. Specs owned by the platform workspace are
left shared: the deployment supplies them to every workspace on purpose.

Downgrade restores the global key and fails if two workspaces now hold a spec
for the same model; the copies are not merged back.

Revision ID: 20260925_1200_model_specs_ws_uq
Revises: 20260924_1200_payment_idem_key
Create Date: 2026-09-25 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260925_1200_model_specs_ws_uq"
down_revision: str | None = "20260924_1200_payment_idem_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GLOBAL = "uq_model_specs_provider_model"
_PER_WORKSPACE = "uq_model_specs_workspace_provider_model"


def upgrade() -> None:
    op.drop_constraint(_GLOBAL, "model_specs", type_="unique")
    op.create_unique_constraint(
        _PER_WORKSPACE, "model_specs", ["workspace_id", "provider_spec_id", "model_name"]
    )

    op.execute(
        """
        INSERT INTO model_specs (
            id, provider_spec_id, model_name, display_name, description,
            context_window, max_output_tokens, input_cost_per_token,
            output_cost_per_token, supports_function_calling, supports_vision,
            supports_reasoning, default_context_strategy, is_active,
            workspace_id, created_by, created_at, updated_at
        )
        SELECT DISTINCT ON (mi.workspace_id, ms.id)
            gen_random_uuid(), ms.provider_spec_id, ms.model_name, ms.display_name,
            ms.description, ms.context_window, ms.max_output_tokens,
            ms.input_cost_per_token, ms.output_cost_per_token,
            ms.supports_function_calling, ms.supports_vision, ms.supports_reasoning,
            ms.default_context_strategy, ms.is_active,
            mi.workspace_id, mi.created_by, now(), now()
        FROM model_instances mi
        JOIN model_specs ms ON ms.id = mi.model_spec_id
        WHERE ms.workspace_id <> mi.workspace_id
          AND ms.workspace_id <> 'platform'
        ORDER BY mi.workspace_id, ms.id, mi.created_at
        ON CONFLICT ON CONSTRAINT uq_model_specs_workspace_provider_model DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE model_instances mi
        SET model_spec_id = own.id
        FROM model_specs ms, model_specs own
        WHERE ms.id = mi.model_spec_id
          AND ms.workspace_id <> mi.workspace_id
          AND ms.workspace_id <> 'platform'
          AND own.workspace_id = mi.workspace_id
          AND own.provider_spec_id = ms.provider_spec_id
          AND own.model_name = ms.model_name
        """
    )


def downgrade() -> None:
    op.drop_constraint(_PER_WORKSPACE, "model_specs", type_="unique")
    op.create_unique_constraint(_GLOBAL, "model_specs", ["provider_spec_id", "model_name"])
