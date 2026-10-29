"""How a provider's HTTP API differs from the next one's, as data.

Providers disagree on a handful of things: where their API lives, which wire
protocol it speaks, how the key is presented, and where and in what shape the
model list comes back. Each provider spec carries these values (``provider_specs``,
fed from the registry catalog), so a provider that speaks a protocol the platform
already has needs a catalog entry, not code.

A self-hosted provider has no address to guess: its ``base_url`` is ``None``,
which is what makes ``requires_endpoint_url`` true.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


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


class Transport(StrEnum):
    """The wire protocol the platform speaks to a provider's chat API."""

    OPENAI = "openai"
    """``/chat/completions`` with SSE streaming: OpenAI and everyone compatible with it."""
    ANTHROPIC = "anthropic"
    """Anthropic's native Messages API, ``/messages``."""


class ReasoningParam(StrEnum):
    """How a request states the reasoning effort it wants."""

    EFFORT = "reasoning_effort"
    """Top-level ``reasoning_effort``: OpenAI and most compatible APIs."""
    OBJECT = "reasoning"
    """``reasoning: {"effort": ...}``: OpenRouter, and gateways in front of it."""


class ModelListShape(StrEnum):
    """The payload shape a provider's model-list endpoint returns."""

    DATA_ID = "data_id"
    """``{"data": [{"id": ...}]}`` — the OpenAI-compatible listing."""

    MODELS_NAME = "models_name"
    """``{"models": [{"name": ...}]}``."""


_ANTHROPIC_API_VERSION = "2023-06-01"


def _with_scheme(url: str) -> str:
    url = url.rstrip("/")
    return url if url.startswith(("http://", "https://")) else f"http://{url}"


@dataclass(frozen=True)
class ProviderProfile:
    """One provider's HTTP contract.

    Args:
        base_url: The API root that ``/chat/completions`` (or ``/messages``) and
            ``/models`` are appended to, e.g. ``https://api.openai.com/v1``, or
            ``None`` when only the operator knows the address.
        transport: The protocol its chat API speaks.
        auth: How to present the key.
        models_path: Path appended to the address itself (not the API root) to
            list models, for providers whose listing is not ``/models`` under the
            API root (Ollama's ``/api/tags``).
        list_shape: How to read the model list back.
        models_query: Query string for the model list. OpenRouter's lists only
            text models unless asked for every output modality, which is where
            its image, video and decision models are.
        reasoning_param: How a request states its reasoning effort.
    """

    base_url: str | None = None
    transport: Transport = Transport.OPENAI
    auth: AuthStyle = AuthStyle.BEARER
    models_path: str | None = None
    list_shape: ModelListShape = ModelListShape.DATA_ID
    models_query: str | None = None
    reasoning_param: ReasoningParam = ReasoningParam.EFFORT

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> ProviderProfile:
        """A profile from stored values (a provider spec row, a cached config)."""
        data = data or {}
        return cls(
            base_url=data.get("base_url") or None,
            transport=Transport(data.get("transport") or Transport.OPENAI),
            auth=AuthStyle(data.get("auth") or AuthStyle.BEARER),
            models_path=data.get("models_path") or None,
            list_shape=ModelListShape(data.get("list_shape") or ModelListShape.DATA_ID),
            models_query=data.get("models_query") or None,
            reasoning_param=ReasoningParam(data.get("reasoning_param") or ReasoningParam.EFFORT),
        )

    def as_mapping(self) -> dict[str, Any]:
        return {
            key: str(value) if value is not None else None for key, value in asdict(self).items()
        }

    @property
    def requires_endpoint_url(self) -> bool:
        """True when the provider is self-hosted and only the operator knows where."""
        return self.base_url is None

    @property
    def requires_api_key(self) -> bool:
        """True when the provider authenticates callers at all."""
        return self.auth is not AuthStyle.NONE

    def api_root(self, endpoint_url: str | None) -> str | None:
        """The API root a call goes to, or None when there is no address.

        An ``endpoint_url`` someone typed may be the server root or the ``/v1``
        base; both are accepted. The catalog's ``base_url`` is used exactly.
        """
        if endpoint_url:
            root = _with_scheme(endpoint_url)
            return root if root.endswith("/v1") else f"{root}/v1"
        return self.base_url.rstrip("/") if self.base_url else None

    def resolve_api_url(self, endpoint_url: str | None, path: str) -> str | None:
        """Full URL of an API path such as ``/chat/completions``, or None when there is no base."""
        root = self.api_root(endpoint_url)
        return f"{root}{path}" if root else None

    def resolve_models_url(self, endpoint_url: str | None) -> str | None:
        """Full model-list URL for this provider, or None when there is no base."""
        if self.models_path:
            address = endpoint_url or self.base_url
            if not address:
                return None
            url = f"{_with_scheme(address)}{self.models_path}"
        else:
            root = self.api_root(endpoint_url)
            if root is None:
                return None
            url = f"{root}/models"
        return f"{url}?{self.models_query}" if self.models_query else url

    def reasoning_fields(self, effort: str | None) -> dict[str, object]:
        """The request fields that ask for ``effort``, empty when none is set."""
        if not effort:
            return {}
        if self.reasoning_param is ReasoningParam.OBJECT:
            return {"reasoning": {"effort": effort}}
        return {"reasoning_effort": effort}

    def build_headers(self, api_key: str | None) -> dict[str, str]:
        """Auth headers for this provider, empty when there is nothing to send."""
        if not api_key or self.auth is AuthStyle.NONE:
            return {}
        if self.auth is AuthStyle.API_KEY_HEADER:
            return {"x-api-key": api_key, "anthropic-version": _ANTHROPIC_API_VERSION}
        return {"Authorization": f"Bearer {api_key}"}


# A provider spec that carries no values: OpenAI-compatible, address supplied by
# whoever configures it.
DEFAULT_PROFILE = ProviderProfile()
