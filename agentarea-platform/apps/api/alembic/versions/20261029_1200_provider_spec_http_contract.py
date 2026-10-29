"""provider_specs carry their HTTP contract: base_url, transport, auth, model listing (ADR-0049)

Until now the platform knew where each provider's API lives from a table in code
(and before that from LiteLLM). The values move onto the spec, fed from the registry
catalog, so an OpenAI-compatible provider is a catalog entry, not a release.

The rows that exist get the values the code table held, so calls keep their
address before the catalog is republished with these fields. A provider not
listed keeps base_url null: it is OpenAI-compatible and needs an endpoint_url.

Revision ID: 20261029_1200_provider_http
Revises: 20261028_1200_signup_attribution
Create Date: 2026-10-29 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261029_1200_provider_http"
down_revision: str | None = "20261028_1200_signup_attribution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# provider identifier -> (base_url, transport, auth, models_path, list_shape, models_query)
_CONTRACTS: dict[str, tuple[str | None, str, str, str | None, str, str | None]] = {
    "openai": ("https://api.openai.com/v1", "openai", "bearer", None, "data_id", None),
    "openrouter": (
        "https://openrouter.ai/api/v1",
        "openai",
        "bearer",
        None,
        "data_id",
        "output_modalities=all",
    ),
    "anthropic": (
        "https://api.anthropic.com/v1",
        "anthropic",
        "api_key_header",
        None,
        "data_id",
        None,
    ),
    "ollama": (None, "openai", "none", "/api/tags", "models_name", None),
    "ollama_chat": (None, "openai", "none", "/api/tags", "models_name", None),
    "mistral": ("https://api.mistral.ai/v1", "openai", "bearer", None, "data_id", None),
    "groq": ("https://api.groq.com/openai/v1", "openai", "bearer", None, "data_id", None),
    "together": ("https://api.together.xyz/v1", "openai", "bearer", None, "data_id", None),
    "together_ai": ("https://api.together.xyz/v1", "openai", "bearer", None, "data_id", None),
    "fireworks": (
        "https://api.fireworks.ai/inference/v1",
        "openai",
        "bearer",
        None,
        "data_id",
        None,
    ),
    "fireworks_ai": (
        "https://api.fireworks.ai/inference/v1",
        "openai",
        "bearer",
        None,
        "data_id",
        None,
    ),
    "deepseek": ("https://api.deepseek.com/v1", "openai", "bearer", None, "data_id", None),
    "perplexity": ("https://api.perplexity.ai", "openai", "bearer", None, "data_id", None),
    "cerebras": ("https://api.cerebras.ai/v1", "openai", "bearer", None, "data_id", None),
    "xai": ("https://api.x.ai/v1", "openai", "bearer", None, "data_id", None),
    "zai": ("https://api.z.ai/api/paas/v4", "openai", "bearer", None, "data_id", None),
    "ai21": ("https://api.ai21.com/studio/v1", "openai", "bearer", None, "data_id", None),
    "ai21_chat": ("https://api.ai21.com/studio/v1", "openai", "bearer", None, "data_id", None),
    "baseten": ("https://inference.baseten.co/v1", "openai", "bearer", None, "data_id", None),
    "codestral": ("https://codestral.mistral.ai/v1", "openai", "bearer", None, "data_id", None),
    "cohere": (
        "https://api.cohere.ai/compatibility/v1",
        "openai",
        "bearer",
        None,
        "data_id",
        None,
    ),
    "cohere_chat": (
        "https://api.cohere.ai/compatibility/v1",
        "openai",
        "bearer",
        None,
        "data_id",
        None,
    ),
    "crusoe": (
        "https://managed-inference-api-proxy.crusoecloud.com/v1",
        "openai",
        "bearer",
        None,
        "data_id",
        None,
    ),
    "dashscope": (
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "openai",
        "bearer",
        None,
        "data_id",
        None,
    ),
    "deepinfra": (
        "https://api.deepinfra.com/v1/openai",
        "openai",
        "bearer",
        None,
        "data_id",
        None,
    ),
    "featherless_ai": ("https://api.featherless.ai/v1", "openai", "bearer", None, "data_id", None),
    "friendliai": (
        "https://api.friendli.ai/serverless/v1",
        "openai",
        "bearer",
        None,
        "data_id",
        None,
    ),
    "gemini": (
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "openai",
        "bearer",
        None,
        "data_id",
        None,
    ),
    "gmi": ("https://api.gmi-serving.com/v1", "openai", "bearer", None, "data_id", None),
    "gradient_ai": ("https://inference.do-ai.run/v1", "openai", "bearer", None, "data_id", None),
    "meta_llama": ("https://api.llama.com/compat/v1", "openai", "bearer", None, "data_id", None),
    "minimax": ("https://api.minimax.io/v1", "openai", "bearer", None, "data_id", None),
    "moonshot": ("https://api.moonshot.ai/v1", "openai", "bearer", None, "data_id", None),
    "morph": ("https://api.morphllm.com/v1", "openai", "bearer", None, "data_id", None),
    "nebius": ("https://api.studio.nebius.ai/v1", "openai", "bearer", None, "data_id", None),
    "novita": ("https://api.novita.ai/v3/openai", "openai", "bearer", None, "data_id", None),
    "nscale": ("https://inference.api.nscale.com/v1", "openai", "bearer", None, "data_id", None),
    "publicai": ("https://api.publicai.co/v1", "openai", "bearer", None, "data_id", None),
    "sambanova": ("https://api.sambanova.ai/v1", "openai", "bearer", None, "data_id", None),
    "sarvam": ("https://api.sarvam.ai/v1", "openai", "bearer", None, "data_id", None),
    "vercel_ai_gateway": (
        "https://ai-gateway.vercel.sh/v1",
        "openai",
        "bearer",
        None,
        "data_id",
        None,
    ),
    "volcengine": (
        "https://ark.cn-beijing.volces.com/api/v3",
        "openai",
        "bearer",
        None,
        "data_id",
        None,
    ),
    "wandb": ("https://api.inference.wandb.ai/v1", "openai", "bearer", None, "data_id", None),
}

_COLUMNS = ("base_url", "transport", "auth", "models_path", "list_shape", "models_query")


def upgrade() -> None:
    op.add_column("provider_specs", sa.Column("base_url", sa.String(), nullable=True))
    op.add_column(
        "provider_specs",
        sa.Column("transport", sa.String(16), nullable=False, server_default="openai"),
    )
    op.add_column(
        "provider_specs",
        sa.Column("auth", sa.String(16), nullable=False, server_default="bearer"),
    )
    op.add_column("provider_specs", sa.Column("models_path", sa.String(), nullable=True))
    op.add_column(
        "provider_specs",
        sa.Column("list_shape", sa.String(16), nullable=False, server_default="data_id"),
    )
    op.add_column("provider_specs", sa.Column("models_query", sa.String(), nullable=True))

    bind = op.get_bind()
    set_clause = (
        "SET base_url = :base_url, transport = :transport, auth = :auth, "
        "models_path = :models_path, list_shape = :list_shape, models_query = :models_query "
    )
    by_key = sa.text("UPDATE provider_specs " + set_clause + "WHERE provider_key = :identifier")
    # A spec a workspace added under its own key still names the provider it
    # speaks to in provider_type. "openai" is skipped there: it is also how the
    # OpenAI-compatible gateways (AgentArea's among them) are typed, and those
    # have no public address to inherit.
    by_type = sa.text(
        "UPDATE provider_specs "
        + set_clause
        + "WHERE provider_type = :identifier AND provider_type <> 'openai' "
        "AND provider_key NOT IN :listed"
    ).bindparams(sa.bindparam("listed", expanding=True))
    listed = list(_CONTRACTS)
    for identifier, contract in _CONTRACTS.items():
        values = dict(zip(_COLUMNS, contract, strict=True))
        bind.execute(by_key, {"identifier": identifier, **values})
        bind.execute(by_type, {"identifier": identifier, "listed": listed, **values})


def downgrade() -> None:
    for column in reversed(_COLUMNS):
        op.drop_column("provider_specs", column)
