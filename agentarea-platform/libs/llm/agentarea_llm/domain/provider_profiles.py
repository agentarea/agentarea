"""How each LLM provider's HTTP API differs, as data.

Providers disagree on four things: where their API lives, what path lists
models, how the key is presented, and what the model list looks like coming
back. That is provider *data*, so it lives in one table instead of as
``if provider == "..."`` branches spread across the discovery service, the
model-test endpoint, and the trigger condition evaluator — each of which had
grown its own copy of "ollama is special".

A self-hosted provider has no address to guess: its ``base_url`` is ``None``,
which is what makes ``requires_endpoint_url`` true. Nothing here names a
provider outside the table itself.

The eventual home for this is ``provider_specs`` (fed from the registry
catalog, ADR-003), so a new provider needs no code change at all. Until those
columns exist, this table is the single source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class AuthStyle(StrEnum):
    """How the API key is presented to the provider."""

    BEARER = "bearer"
    """``Authorization: Bearer <key>`` — the OpenAI-compatible default."""

    # The scanner matches API_KEY in the name; the value is the name of an auth
    # style, not a credential.
    API_KEY_HEADER = "api_key_header"  # pragma: allowlist secret
    """A vendor header (``x-api-key``) plus a pinned API version."""

    NONE = "none"
    """No credential: the endpoint is reached over the network the user controls."""


class ModelListShape(StrEnum):
    """The payload shape a provider's model-list endpoint returns."""

    DATA_ID = "data_id"
    """``{"data": [{"id": ...}]}`` — the OpenAI-compatible listing."""

    MODELS_NAME = "models_name"
    """``{"models": [{"name": ...}]}``."""


@dataclass(frozen=True)
class ProviderProfile:
    """One provider's HTTP contract.

    Args:
        base_url: Public API root, or ``None`` when only the operator knows it.
        models_path: Path appended to ``base_url`` to list models. ``None``
            selects the OpenAI-compatible rule: ``/models`` when the base
            already ends in ``/v1``, otherwise ``/v1/models``.
        auth: How to present the key.
        list_shape: How to read the model list back.
        aliases: Other identifiers the same provider answers to — notably the
            LiteLLM ``provider_type`` (``ollama_chat``) next to the catalog's
            ``provider_key`` (``ollama``). Callers hold one or the other
            depending on where they sit, and neither should have to convert.
    """

    base_url: str | None = None
    models_path: str | None = None
    auth: AuthStyle = AuthStyle.BEARER
    list_shape: ModelListShape = ModelListShape.DATA_ID
    aliases: tuple[str, ...] = field(default_factory=tuple)

    @property
    def requires_endpoint_url(self) -> bool:
        """True when the provider is self-hosted and only the operator knows where."""
        return self.base_url is None

    @property
    def requires_api_key(self) -> bool:
        """True when the provider authenticates callers at all."""
        return self.auth is not AuthStyle.NONE

    def resolve_models_url(self, endpoint_url: str | None) -> str | None:
        """Full model-list URL for this provider, or None when there is no base."""
        base = (endpoint_url or self.base_url or "").rstrip("/")
        if not base:
            return None
        if self.models_path:
            return f"{base}{self.models_path}"
        return f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"

    def build_headers(self, api_key: str | None) -> dict[str, str]:
        """Auth headers for this provider, empty when there is nothing to send."""
        if not api_key or self.auth is AuthStyle.NONE:
            return {}
        if self.auth is AuthStyle.API_KEY_HEADER:
            return {"x-api-key": api_key, "anthropic-version": _ANTHROPIC_API_VERSION}
        return {"Authorization": f"Bearer {api_key}"}


_ANTHROPIC_API_VERSION = "2023-06-01"

# Unknown providers get this: no address to guess, so the operator supplies the
# endpoint, and we assume the OpenAI-compatible contract everyone else follows.
DEFAULT_PROFILE = ProviderProfile()

PROVIDER_PROFILES: dict[str, ProviderProfile] = {
    "openai": ProviderProfile(base_url="https://api.openai.com"),
    "openrouter": ProviderProfile(base_url="https://openrouter.ai/api"),
    "anthropic": ProviderProfile(
        base_url="https://api.anthropic.com", auth=AuthStyle.API_KEY_HEADER
    ),
    "mistral": ProviderProfile(base_url="https://api.mistral.ai"),
    "groq": ProviderProfile(base_url="https://api.groq.com/openai"),
    "together": ProviderProfile(base_url="https://api.together.xyz"),
    "fireworks": ProviderProfile(base_url="https://api.fireworks.ai/inference"),
    "deepseek": ProviderProfile(base_url="https://api.deepseek.com"),
    "perplexity": ProviderProfile(base_url="https://api.perplexity.ai"),
    "cerebras": ProviderProfile(base_url="https://api.cerebras.ai"),
    "xai": ProviderProfile(base_url="https://api.x.ai"),
    "zai": ProviderProfile(base_url="https://api.z.ai/api/paas/v4", models_path="/models"),
    "ollama": ProviderProfile(
        base_url=None,
        models_path="/api/tags",
        auth=AuthStyle.NONE,
        list_shape=ModelListShape.MODELS_NAME,
        aliases=("ollama_chat",),
    ),
}

_BY_IDENTIFIER: dict[str, ProviderProfile] = {
    identifier: profile
    for key, profile in PROVIDER_PROFILES.items()
    for identifier in (key, *profile.aliases)
}


def profile_for(provider: str | None) -> ProviderProfile:
    """Profile for a ``provider_key`` or a LiteLLM ``provider_type``.

    Unknown providers fall back to the OpenAI-compatible default rather than
    raising: a provider added to the catalog before this table must still be
    configurable, it just has to carry its own endpoint.
    """
    if not provider:
        return DEFAULT_PROFILE
    return _BY_IDENTIFIER.get(provider, DEFAULT_PROFILE)
