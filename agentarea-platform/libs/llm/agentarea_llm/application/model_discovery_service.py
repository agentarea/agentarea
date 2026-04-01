import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

# Provider-specific base URLs for /v1/models discovery
_PROVIDER_BASE_URLS: dict[str, str] = {
    "openrouter": "https://openrouter.ai/api",
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
    "mistral": "https://api.mistral.ai",
    "groq": "https://api.groq.com/openai",
    "together": "https://api.together.xyz",
    "fireworks": "https://api.fireworks.ai/inference",
    "deepseek": "https://api.deepseek.com",
    "perplexity": "https://api.perplexity.ai",
    "cerebras": "https://api.cerebras.ai",
    "xai": "https://api.x.ai",
    "ollama": "http://localhost:11434",
    "zai": "https://api.z.ai/api/paas/v4",
}


@dataclass
class DiscoveredModel:
    model_name: str
    display_name: str
    context_window: int = 4096
    description: str = ""
    max_output_tokens: int = 4096
    input_cost_per_token: float = 0.0
    output_cost_per_token: float = 0.0
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

    def __init__(self, timeout: int = 30):
        self._timeout = timeout

    def _build_url(self, provider_key: str, endpoint_url: str | None) -> str | None:
        base = endpoint_url or _PROVIDER_BASE_URLS.get(provider_key, "")
        if not base:
            return None
        base = base.rstrip("/")
        if provider_key == "ollama":
            return f"{base}/api/tags"
        if provider_key == "zai":
            return f"{base}/models"
        if base.endswith("/v1"):
            return f"{base}/models"
        return f"{base}/v1/models"

    def _build_headers(self, provider_key: str, api_key: str) -> dict[str, str]:
        if provider_key == "anthropic":
            return {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            }
        if provider_key == "ollama":
            return {}
        return {"Authorization": f"Bearer {api_key}"}

    def _parse_response(self, provider_key: str, data: dict) -> list[DiscoveredModel]:
        models: list[DiscoveredModel] = []
        if provider_key == "ollama":
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
            models.append(
                DiscoveredModel(
                    model_name=model_id,
                    display_name=m.get("name", model_id),
                    context_window=m.get("context_length", 4096),
                    description=m.get("description", ""),
                )
            )
        return models

    async def discover(
        self,
        provider_key: str,
        api_key: str,
        endpoint_url: str | None = None,
    ) -> list[DiscoveredModel]:
        url = self._build_url(provider_key, endpoint_url)
        if not url:
            logger.warning("No base URL for provider %s and no endpoint_url provided", provider_key)
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
