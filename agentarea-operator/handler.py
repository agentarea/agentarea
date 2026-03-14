"""AgentArea K8s Operator — syncs LLMProviderConfig CRDs to the database.

Watches LLMProviderConfig resources and:
1. Reads API key from referenced K8s Secret
2. Upserts ProviderConfig in the database
3. Optionally discovers models via /v1/models
4. Creates ModelInstance entries for each activated model

Env vars:
    DATABASE_URL       – PostgreSQL async connection string
    WATCH_NAMESPACE    – Namespace to watch (default: all)
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import httpx
import kopf
from kubernetes import client as k8s_client
from sqlalchemy import create_engine, text

logger = logging.getLogger("agentarea-operator")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://user:password@localhost:5432/agentarea",
)
engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def read_secret(namespace: str, secret_name: str, secret_key: str) -> str:
    """Read a value from a Kubernetes Secret."""
    v1 = k8s_client.CoreV1Api()
    secret = v1.read_namespaced_secret(name=secret_name, namespace=namespace)
    import base64

    raw = secret.data.get(secret_key)
    if raw is None:
        raise kopf.PermanentError(
            f"Key '{secret_key}' not found in Secret '{secret_name}'"
        )
    return base64.b64decode(raw).decode("utf-8")


def discover_models(
    provider_key: str, api_key: str, endpoint_url: str | None
) -> list[dict]:
    """Call provider's /v1/models endpoint and return list of model dicts."""
    # Provider-specific base URLs
    base_urls = {
        "openrouter": "https://openrouter.ai/api",
        "openai": "https://api.openai.com",
        "anthropic": "https://api.anthropic.com",
        "mistral": "https://api.mistral.ai",
        "groq": "https://api.groq.com/openai",
        "together": "https://api.together.xyz",
        "fireworks": "https://api.fireworks.ai/inference",
        "deepseek": "https://api.deepseek.com",
        "perplexity": "https://api.perplexity.ai",
    }
    base = endpoint_url or base_urls.get(provider_key, "")
    if not base:
        logger.warning("No base URL for provider %s, skipping discovery", provider_key)
        return []

    url = f"{base.rstrip('/')}/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}

    # Anthropic uses a different auth header
    if provider_key == "anthropic":
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        url = f"{base.rstrip('/')}/v1/models"

    try:
        resp = httpx.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        models = []
        for m in data.get("data", []):
            model_id = m.get("id", "")
            models.append(
                {
                    "model_name": model_id,
                    "display_name": m.get("name", model_id),
                    "context_window": m.get("context_length", 4096),
                    "description": m.get("description", ""),
                }
            )
        logger.info("Discovered %d models from %s", len(models), provider_key)
        return models
    except Exception as e:
        logger.error("Model discovery failed for %s: %s", provider_key, e)
        return []


def sync_provider_config(
    spec: dict,
    api_key: str,
    cr_name: str,
) -> tuple[str, int]:
    """Sync a ProviderConfig + optional models to the database.

    Returns (provider_config_id, model_count).
    """
    provider_key = spec["providerKey"]
    name = spec["name"]
    endpoint_url = spec.get("endpointUrl")
    is_public = spec.get("isPublic", True)
    workspace_id = spec.get("workspaceId", "system")
    discover = spec.get("discoverModels", False)
    explicit_models = spec.get("models", [])

    with engine.begin() as conn:
        # 1. Find the ProviderSpec by provider_key
        row = conn.execute(
            text("SELECT id FROM provider_specs WHERE provider_key = :key"),
            {"key": provider_key},
        ).fetchone()
        if not row:
            raise kopf.PermanentError(
                f"ProviderSpec with key '{provider_key}' not found"
            )
        provider_spec_id = str(row[0])

        # 2. Upsert ProviderConfig (match by name + workspace)
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
                    "UPDATE provider_configs SET "
                    "api_key = :key, endpoint_url = :url, "
                    "is_active = true, is_public = :pub, updated_at = now() "
                    "WHERE id = :id"
                ),
                {
                    "id": config_id,
                    "key": api_key,
                    "url": endpoint_url,
                    "pub": is_public,
                },
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

        # 3. Model discovery or explicit model activation
        model_count = 0

        if discover:
            discovered = discover_models(provider_key, api_key, endpoint_url)
            for m in discovered:
                _upsert_model_spec_and_instance(
                    conn, provider_spec_id, config_id, m, workspace_id
                )
            model_count = len(discovered)
        elif explicit_models:
            for em in explicit_models:
                model_name = em["modelName"]
                # Find the model spec
                ms_row = conn.execute(
                    text(
                        "SELECT id FROM model_specs "
                        "WHERE provider_spec_id = :spec_id AND model_name = :mn"
                    ),
                    {"spec_id": provider_spec_id, "mn": model_name},
                ).fetchone()
                if ms_row:
                    _upsert_model_instance(
                        conn, config_id, str(ms_row[0]), model_name, workspace_id
                    )
                    model_count += 1

    return config_id, model_count


def _upsert_model_spec_and_instance(
    conn, provider_spec_id: str, config_id: str, model: dict, workspace_id: str
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

    _upsert_model_instance(conn, config_id, model_spec_id, model_name, workspace_id)


def _upsert_model_instance(
    conn, config_id: str, model_spec_id: str, model_name: str, workspace_id: str
):
    """Create a ModelInstance if it doesn't already exist."""
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


# ─── Kopf handlers ───────────────────────────────────────────────


@kopf.on.create("agentarea.io", "v1alpha1", "llmproviderconfigs")
@kopf.on.update("agentarea.io", "v1alpha1", "llmproviderconfigs")
def on_provider_config_change(spec, meta, status, namespace, patch, **_):
    """Handle create/update of LLMProviderConfig."""
    cr_name = meta["name"]
    logger.info("Syncing LLMProviderConfig %s/%s", namespace, cr_name)

    # Read API key from Secret
    secret_ref = spec.get("apiKeySecretRef")
    if not secret_ref:
        patch.status["phase"] = "Error"
        patch.status["message"] = "apiKeySecretRef is required"
        return

    try:
        api_key = read_secret(namespace, secret_ref["name"], secret_ref["key"])
    except Exception as e:
        patch.status["phase"] = "Error"
        patch.status["message"] = f"Failed to read secret: {e}"
        raise kopf.TemporaryError(str(e), delay=30)

    if spec.get("discoverModels"):
        patch.status["phase"] = "Discovering"
        patch.status["message"] = "Discovering models..."

    try:
        config_id, model_count = sync_provider_config(spec, api_key, cr_name)
    except kopf.PermanentError:
        raise
    except Exception as e:
        patch.status["phase"] = "Error"
        patch.status["message"] = str(e)
        raise kopf.TemporaryError(str(e), delay=60)

    patch.status["phase"] = "Synced"
    patch.status["providerConfigId"] = config_id
    patch.status["discoveredModels"] = model_count
    patch.status["lastSyncedAt"] = datetime.now(timezone.utc).isoformat()
    patch.status["message"] = (
        f"Synced with {model_count} models"
        if model_count
        else "Synced (no models)"
    )
    logger.info(
        "Synced %s/%s → config=%s, models=%d",
        namespace, cr_name, config_id, model_count,
    )


@kopf.on.delete("agentarea.io", "v1alpha1", "llmproviderconfigs")
def on_provider_config_delete(spec, meta, namespace, **_):
    """Handle deletion — deactivate (don't delete) the ProviderConfig."""
    cr_name = meta["name"]
    name = spec["name"]
    workspace_id = spec.get("workspaceId", "system")

    logger.info("Deactivating LLMProviderConfig %s/%s", namespace, cr_name)

    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE provider_configs SET is_active = false, "
                    "updated_at = now() WHERE name = :name AND workspace_id = :ws"
                ),
                {"name": name, "ws": workspace_id},
            )
    except Exception as e:
        logger.error("Failed to deactivate %s: %s", cr_name, e)


@kopf.on.timer("agentarea.io", "v1alpha1", "llmproviderconfigs", interval=3600)
def periodic_rediscovery(spec, meta, namespace, patch, **_):
    """Re-discover models every hour for configs with discoverModels=true."""
    if not spec.get("discoverModels"):
        return

    cr_name = meta["name"]
    logger.info("Periodic rediscovery for %s/%s", namespace, cr_name)

    secret_ref = spec.get("apiKeySecretRef")
    if not secret_ref:
        return

    try:
        api_key = read_secret(namespace, secret_ref["name"], secret_ref["key"])
        config_id, model_count = sync_provider_config(spec, api_key, cr_name)
        patch.status["phase"] = "Synced"
        patch.status["discoveredModels"] = model_count
        patch.status["lastSyncedAt"] = datetime.now(timezone.utc).isoformat()
        patch.status["message"] = f"Re-synced with {model_count} models"
    except Exception as e:
        logger.error("Periodic rediscovery failed for %s: %s", cr_name, e)
        patch.status["message"] = f"Rediscovery failed: {e}"
