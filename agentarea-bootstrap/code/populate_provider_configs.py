"""Populate LLM provider configs from Helm values (IaaC).

Reads PROVIDER_CONFIGS env var — a JSON array:
  [
    {
      "name": "OpenRouter",
      "providerKey": "openrouter",
      "endpointUrl": "https://openrouter.ai/api/v1",
      "apiKey": "sk-or-...",
      "discoverModels": true,
      "isPublic": true
    }
  ]

For each config:
  1. Find the ProviderSpec by providerKey
  2. Upsert ProviderConfig (name + workspace_id=system)
  3. If discoverModels: call /v1/models, upsert ModelSpecs + ModelInstances

Env vars:
    PROVIDER_CONFIGS  – JSON array. Empty = skip.
"""

import json
import os
import uuid

import httpx
from code.db import engine
from sqlalchemy import text
from sqlalchemy.engine import Connection

PROVIDER_CONFIGS = os.environ.get("PROVIDER_CONFIGS", os.environ.get("PROVIDER_CONFIGS", ""))

# Provider-specific base URLs for /v1/models discovery
_PROVIDER_BASE_URLS = {
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
}


def discover_models(
    provider_key: str, api_key: str, endpoint_url: str | None
) -> list[dict]:
    """Call provider's /v1/models endpoint."""
    base = endpoint_url or _PROVIDER_BASE_URLS.get(provider_key, "")
    if not base:
        return []

    base = base.rstrip("/")
    # If endpoint already ends with /v1, just append /models
    if base.endswith("/v1"):
        url = f"{base}/models"
    else:
        url = f"{base}/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}

    if provider_key == "anthropic":
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}

    try:
        resp = httpx.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        models = []
        for m in data.get("data", []):
            model_id = m.get("id", "")
            models.append({
                "model_name": model_id,
                "display_name": m.get("name", model_id),
                "context_window": m.get("context_length", 4096),
                "description": m.get("description", ""),
            })
        return models
    except Exception as e:
        print(f"    Model discovery failed for {provider_key}: {e}")
        return []


def upsert_provider_config(conn: Connection, config: dict) -> tuple[str, int]:
    """Upsert a ProviderConfig + optional models. Returns (config_id, model_count)."""
    provider_key = config["providerKey"]
    name = config["name"]
    # Resolve API key: inline apiKey or from env var via apiKeyFromEnv
    api_key = config.get("apiKey", "")
    if not api_key and config.get("apiKeyFromEnv"):
        api_key = os.environ.get(config["apiKeyFromEnv"], "")
    if not api_key:
        print(f"    No API key for '{name}' — skipping")
        return ("", 0)
    endpoint_url = config.get("endpointUrl")
    is_public = config.get("isPublic", True)
    workspace_id = config.get("workspaceId", "system")
    do_discover = config.get("discoverModels", False)

    # Find ProviderSpec
    row = conn.execute(
        text("SELECT id FROM provider_specs WHERE provider_key = :key"),
        {"key": provider_key},
    ).fetchone()
    if not row:
        print(f"    ProviderSpec '{provider_key}' not found — skipping")
        return ("", 0)
    provider_spec_id = str(row[0])

    # Upsert ProviderConfig
    existing = conn.execute(
        text(
            "SELECT id FROM provider_configs "
            "WHERE name = :name AND workspace_id = :ws"
        ),
        {"name": name, "ws": workspace_id},
    ).fetchone()

    if existing:
        config_id = str(existing[0])
        conn.execute(
            text(
                "UPDATE provider_configs SET api_key = :key, endpoint_url = :url, "
                "is_active = true, is_public = :pub, updated_at = now() "
                "WHERE id = :id"
            ),
            {"id": config_id, "key": api_key, "url": endpoint_url, "pub": is_public},
        )
    else:
        config_id = str(uuid.uuid4())
        conn.execute(
            text(
                "INSERT INTO provider_configs "
                "(id, provider_spec_id, name, api_key, endpoint_url, "
                "is_active, is_public, workspace_id, created_by, "
                "created_at, updated_at) "
                "VALUES (:id, :spec_id, :name, :key, :url, "
                "true, :pub, :ws, 'system', now(), now())"
            ),
            {
                "id": config_id,
                "spec_id": provider_spec_id,
                "name": name,
                "key": api_key,
                "url": endpoint_url,
                "pub": is_public,
                "ws": workspace_id,
            },
        )

    # Model discovery
    model_count = 0
    if do_discover:
        print(f"    Discovering models for {provider_key}...")
        models = discover_models(provider_key, api_key, endpoint_url)
        for m in models:
            _upsert_model_spec_and_instance(
                conn, provider_spec_id, config_id, m, workspace_id
            )
        model_count = len(models)
        print(f"    Discovered {model_count} models")

    return config_id, model_count


def _upsert_model_spec_and_instance(
    conn: Connection,
    provider_spec_id: str,
    config_id: str,
    model: dict,
    workspace_id: str,
):
    """Create or update a ModelSpec and its ModelInstance."""
    model_name = model["model_name"]

    # Upsert ModelSpec
    ms_row = conn.execute(
        text(
            "SELECT id FROM model_specs "
            "WHERE provider_spec_id = :spec_id AND model_name = :mn"
        ),
        {"spec_id": provider_spec_id, "mn": model_name},
    ).fetchone()

    if ms_row:
        model_spec_id = str(ms_row[0])
        conn.execute(
            text(
                "UPDATE model_specs SET display_name = :dn, "
                "context_window = :cw, updated_at = now() WHERE id = :id"
            ),
            {
                "id": model_spec_id,
                "dn": model.get("display_name", model_name),
                "cw": model.get("context_window", 4096),
            },
        )
    else:
        model_spec_id = str(uuid.uuid4())
        conn.execute(
            text(
                "INSERT INTO model_specs "
                "(id, provider_spec_id, model_name, display_name, description, "
                "context_window, is_active, workspace_id, created_by, "
                "created_at, updated_at) "
                "VALUES (:id, :spec_id, :mn, :dn, :desc, :cw, true, "
                ":ws, 'system', now(), now())"
            ),
            {
                "id": model_spec_id,
                "spec_id": provider_spec_id,
                "mn": model_name,
                "dn": model.get("display_name", model_name),
                "desc": model.get("description", ""),
                "cw": model.get("context_window", 4096),
                "ws": workspace_id,
            },
        )

    # Upsert ModelInstance
    existing = conn.execute(
        text(
            "SELECT id FROM model_instances "
            "WHERE provider_config_id = :cid AND model_spec_id = :msid"
        ),
        {"cid": config_id, "msid": model_spec_id},
    ).fetchone()

    if not existing:
        conn.execute(
            text(
                "INSERT INTO model_instances "
                "(id, provider_config_id, model_spec_id, name, "
                "is_active, is_public, workspace_id, created_by, "
                "created_at, updated_at) "
                "VALUES (:id, :cid, :msid, :name, true, true, "
                ":ws, 'system', now(), now())"
            ),
            {
                "id": str(uuid.uuid4()),
                "cid": config_id,
                "msid": model_spec_id,
                "name": model_name,
                "ws": workspace_id,
            },
        )


def main() -> None:
    """Create provider configs from Helm values."""
    if not PROVIDER_CONFIGS:
        print("  PROVIDER_CONFIGS not set — skipping")
        return

    try:
        configs = json.loads(PROVIDER_CONFIGS)
    except json.JSONDecodeError as e:
        print(f"  Failed to parse PROVIDER_CONFIGS: {e}")
        return

    if not configs:
        print("  No provider configs configured — skipping")
        return

    print(f"  Processing {len(configs)} provider configs")

    with engine.begin() as conn:
        for config in configs:
            name = config.get("name", "unnamed")
            try:
                config_id, model_count = upsert_provider_config(conn, config)
                if config_id:
                    print(f"    '{name}' → {config_id} ({model_count} models)")
            except Exception as e:
                print(f"    Failed '{name}': {e}")


if __name__ == "__main__":
    main()
