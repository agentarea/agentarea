import logging
from dataclasses import dataclass, field

import httpx
from agentarea_common.utils.url_safety import UnsafeUrlError, validate_outbound_url

from ..domain.provider_profiles import ModelListShape, profile_for

logger = logging.getLogger(__name__)


def _positive_int_or_none(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _nonnegative_float_or_none(value) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


@dataclass
class DiscoveredModel:
    model_name: str
    display_name: str
    context_window: int | None = None
    description: str = ""
    max_output_tokens: int | None = None
    input_cost_per_token: float | None = None
    output_cost_per_token: float | None = None
    supports_function_calling: bool = False
    supports_vision: bool = False
    supports_reasoning: bool = False


@dataclass
class DiscoveryResult:
    total_discovered: int = 0
    new_specs: int = 0
    new_instances: int = 0
    models: list[DiscoveredModel] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ModelDiscoveryService:
    """Discovers available models from LLM provider APIs."""

    def __init__(self, timeout: int = 30, allow_private_endpoints: bool = False):
        self._timeout = timeout
        # User-supplied endpoint_url is validated against non-public address
        # classes (SSRF guard). Self-host installs targeting private endpoints
        # can opt out via allow_private_endpoints=True.
        self._allow_private_endpoints = allow_private_endpoints

    def _build_url(self, provider_key: str, endpoint_url: str | None) -> str | None:
        return profile_for(provider_key).resolve_models_url(endpoint_url)

    def _build_headers(self, provider_key: str, api_key: str | None) -> dict[str, str]:
        return profile_for(provider_key).build_headers(api_key)

    def _parse_response(self, provider_key: str, data: dict) -> list[DiscoveredModel]:
        models: list[DiscoveredModel] = []
        if profile_for(provider_key).list_shape is ModelListShape.MODELS_NAME:
            for m in data.get("models", []):
                name = m.get("name", "")
                models.append(
                    DiscoveredModel(
                        model_name=name,
                        display_name=name,
                    )
                )
            return models

        for m in data.get("data", []):
            model_id = m.get("id", "")
            if not model_id:
                continue
            pricing = m.get("pricing") if isinstance(m.get("pricing"), dict) else {}
            top_provider = m.get("top_provider") if isinstance(m.get("top_provider"), dict) else {}
            models.append(
                DiscoveredModel(
                    model_name=model_id,
                    display_name=m.get("name", model_id),
                    context_window=_positive_int_or_none(m.get("context_length")),
                    max_output_tokens=_positive_int_or_none(
                        m.get("max_output_tokens") or top_provider.get("max_completion_tokens")
                    ),
                    input_cost_per_token=_nonnegative_float_or_none(pricing.get("prompt")),
                    output_cost_per_token=_nonnegative_float_or_none(pricing.get("completion")),
                    description=m.get("description", ""),
                )
            )
        return models

    async def discover(
        self,
        provider_key: str,
        api_key: str | None,
        endpoint_url: str | None = None,
    ) -> list[DiscoveredModel]:
        url = self._build_url(provider_key, endpoint_url)
        if not url:
            logger.warning("No base URL for provider %s and no endpoint_url provided", provider_key)
            return []

        # Only the user-supplied endpoint_url is untrusted; built-in provider
        # base URLs (incl. ollama's localhost default) are trusted and skipped.
        if endpoint_url:
            try:
                validate_outbound_url(url, allow_private=self._allow_private_endpoints)
            except UnsafeUrlError:
                # Do not interpolate the user-supplied endpoint/host into the log
                # message (log-injection); the rejection itself is the signal.
                logger.warning("Rejected model-discovery endpoint blocked by outbound SSRF guard")
                return []

        headers = self._build_headers(provider_key, api_key)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                models = self._parse_response(provider_key, data)
                logger.info("Discovered %d models for provider %s", len(models), provider_key)
                return models
        except Exception as e:
            logger.error("Model discovery failed for %s: %s", provider_key, e)
            return []
