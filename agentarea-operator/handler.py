"""AgentArea K8s Operator — syncs LLMProviderConfig CRDs to the database.

Watches LLMProviderConfig resources and:
1. Reads API key from referenced K8s Secret
2. Upserts ProviderConfig in the database
3. Optionally discovers models via /v1/models
4. Creates ModelInstance entries for each activated model

This is the only writer of ``provider_configs.managed_by = 'platform'``. The
application refuses those writes from every path a tenant can reach — the API has
no request field that sets the column, and the repositories re-assert the strict
workspace filter on update and delete — because a tenant able to declare their own
configuration platform-managed could make it visible to every other workspace and
deletable by nobody. Which models a deployment offers, on whose key, is an access
decision, and it is made here: declared as a custom resource wherever the
deployment is described, and reconciled into rows.

Env vars:
    DATABASE_URL                     – PostgreSQL connection string
    SECRET_MANAGER_ENCRYPTION_KEY    – Fernet key, same one the platform uses
    WATCH_NAMESPACE                  – Namespace to watch (default: all)
"""

import logging
import os
import uuid
from datetime import datetime, timezone

import httpx
import kopf
from cryptography.fernet import Fernet
from kubernetes import client as k8s_client
from sqlalchemy import create_engine, text

logger = logging.getLogger("agentarea-operator")

# Keep in sync with agentarea_common.constants
PLATFORM_WORKSPACE_ID = "platform"
PLATFORM_PRINCIPAL_ID = "platform"
MANAGED_BY_PLATFORM = "platform"

# Keep in sync with agentarea_common.platform_ids, which carries the full
# explanation and the test that pins these values.
#
# In short: a platform model's instance id is what an agent stores when it selects
# the model and what billing's rate cards are keyed on — and those rows live in the
# payments service, a different database this process cannot see. Deriving the id
# from (provider_key, model_name) is what lets a rate card name it without anyone
# copying a generated uuid between environments by hand.
PLATFORM_ID_NAMESPACE = uuid.UUID("8f3d4b2a-6c1e-5a7f-9d0b-2e4a6c8f1d3b")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://user:password@localhost:5432/agentarea",
)
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# The same key the platform encrypts workspace secrets with, because this writes
# into the same table it reads from.
#
# Holding it makes this process able to decrypt any row in encrypted_secrets, which
# is more than it needs and more than it should keep. The narrow fix is a database
# role restricted to the tables below — tracked separately; until then this is the
# most privileged thing in the cluster after the API itself, and its RBAC and image
# provenance should be treated that way.
ENCRYPTION_KEY = os.environ.get("SECRET_MANAGER_ENCRYPTION_KEY", "")


def platform_config_id(provider_key: str) -> str:
    return str(uuid.uuid5(PLATFORM_ID_NAMESPACE, f"provider_config:{provider_key}"))


def platform_instance_id(provider_key: str, model_name: str) -> str:
    return str(uuid.uuid5(PLATFORM_ID_NAMESPACE, f"model_instance:{provider_key}:{model_name}"))


def secret_name_for(config_id: str) -> str:
    """The name a configuration's key is stored under.

    ``provider_config_<uuid>`` is a reserved prefix: ``validate_user_secret_name``
    refuses it, and ``parse_managed_name`` reads it back into the owner, which is
    what stops the secrets API offering the row for editing or deletion. Naming it
    anything else would produce a secret a user could claim and overwrite.
    """
    return f"provider_config_{config_id}"


def store_api_key(conn, workspace_id: str, secret_name: str, api_key: str) -> None:
    """Encrypt the key into the workspace's secret store, creating or rotating it.

    Deliberately not stored on ``provider_configs.api_key``, which holds the *name*
    of a secret and is passed to the secret manager as one. Writing the key there
    would put a live credential in plain text in a column every workspace can read
    — the configuration is visible to all of them by design — and the lookup would
    then fail anyway, because no secret exists under a name that is itself a key.
    """
    if not ENCRYPTION_KEY:
        raise kopf.PermanentError(
            "SECRET_MANAGER_ENCRYPTION_KEY is not set; refusing to write a provider "
            "configuration whose credential cannot be stored. Set it to the same "
            "Fernet key the platform API uses."
        )
    encrypted = Fernet(ENCRYPTION_KEY.encode("utf-8")).encrypt(api_key.encode("utf-8")).decode()
    conn.execute(
        text(
            "INSERT INTO encrypted_secrets "
            "(id, workspace_id, secret_name, encrypted_value, owner_type, owner_id, "
            "created_by, created_at, updated_at) "
            "VALUES (:id, :ws, :name, :val, 'provider_config', :owner, :by, now(), now()) "
            "ON CONFLICT (workspace_id, secret_name) DO UPDATE SET "
            "encrypted_value = EXCLUDED.encrypted_value, external_ref = NULL, "
            "updated_by = EXCLUDED.created_by, updated_at = now()"
        ),
        {
            "id": str(uuid.uuid4()),
            "ws": workspace_id,
            "name": secret_name,
            "val": encrypted,
            "owner": secret_name.removeprefix("provider_config_"),
            "by": PLATFORM_PRINCIPAL_ID,
        },
    )


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

    # OpenAI-compatible routers are configured with the version already in the
    # URL; appending it unconditionally produced /v1/v1 and a swallowed 404.
    base = base.rstrip("/")
    url = f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}

    # Anthropic uses a different auth header
    if provider_key == "anthropic":
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

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
    workspace_id = spec.get("workspaceId", PLATFORM_WORKSPACE_ID)
    discover = spec.get("discoverModels", False)
    explicit_models = spec.get("models", [])

    with engine.begin() as conn:
        # 1. Find the ProviderSpec by provider_key
        row = conn.execute(
            text("SELECT id FROM provider_specs WHERE provider_key = :key"),
            {"key": provider_key},
        ).fetchone()
        if not row:
            # Temporary, not permanent: the specs are imported from the published
            # catalog by a separate job, so "not there" is usually "not there yet" —
            # an install whose catalog import has not run, or has not finished. A
            # PermanentError here is never retried, so a resource that arrived one
            # minute early stayed broken until a human touched it, and the only
            # evidence was a line in this process's log.
            #
            # A genuinely wrong provider_key now retries instead of stopping. That
            # costs a log line a minute and reports itself in the resource's status,
            # which is a better failure than silence.
            raise kopf.TemporaryError(
                f"ProviderSpec with key '{provider_key}' not found "
                "(catalog not imported yet?)",
                delay=60,
            )
        provider_spec_id = str(row[0])

        # 2. Upsert ProviderConfig, keyed on its derived id.
        #
        # Not on (name, workspace) as this once was: the name is a display string
        # the custom resource can change, and matching on it meant renaming a CR
        # created a second configuration rather than updating the first — two rows
        # holding the operator's key, both visible to every workspace, only one of
        # them metered.
        is_platform = workspace_id == PLATFORM_WORKSPACE_ID
        config_id = platform_config_id(provider_key) if is_platform else str(uuid.uuid4())
        managed_by = MANAGED_BY_PLATFORM if is_platform else None

        existing = conn.execute(
            text("SELECT id FROM provider_configs WHERE id = :id"),
            {"id": config_id},
        ).fetchone()

        # The configuration stores the NAME of a secret; the key itself goes to the
        # secret store under that name, in the same transaction.
        secret_name = secret_name_for(config_id)
        store_api_key(conn, workspace_id, secret_name, api_key)

        if existing:
            conn.execute(
                text(
                    "UPDATE provider_configs SET "
                    "name = :name, api_key = :key, endpoint_url = :url, "
                    "managed_by = :managed_by, "
                    "is_active = true, is_public = :pub, updated_at = now() "
                    "WHERE id = :id"
                ),
                {
                    "id": config_id,
                    "name": name,
                    "key": secret_name,
                    "url": endpoint_url,
                    "managed_by": managed_by,
                    "pub": is_public,
                },
            )
        else:
            conn.execute(
                text(
                    "INSERT INTO provider_configs "
                    "(id, provider_spec_id, name, api_key, endpoint_url, managed_by, "
                    "is_active, is_public, source, workspace_id, created_by, "
                    "created_at, updated_at) "
                    "VALUES (:id, :spec_id, :name, :key, :url, :managed_by, "
                    "true, :pub, 'official', :ws, :created_by, now(), now())"
                ),
                {
                    "id": config_id,
                    "spec_id": provider_spec_id,
                    "name": name,
                    "key": secret_name,
                    "url": endpoint_url,
                    "managed_by": managed_by,
                    "pub": is_public,
                    "ws": workspace_id,
                    "created_by": PLATFORM_PRINCIPAL_ID,
                },
            )

        # 3. Model discovery or explicit model activation
        model_count = 0

        if discover:
            discovered = discover_models(provider_key, api_key, endpoint_url)
            for m in discovered:
                _upsert_model_spec_and_instance(
                    conn, provider_key, provider_spec_id, config_id, m, workspace_id
                )
            model_count = len(discovered)
        elif explicit_models:
            for em in explicit_models:
                # Creates the model spec when the catalog has none, rather than
                # activating only what is already there.
                #
                # It used to look the spec up and silently do nothing when it was
                # missing, which is the normal case for anything we decide to sell:
                # a model released last month is not in a catalog built from
                # someone else's list. The custom resource went Synced with zero
                # models and the model never appeared, with nothing saying why.
                #
                # Pricing comes from the resource for the same reason. The runtime
                # refuses to run a model whose cost per token is unset, so a spec
                # created without it is a model that lists and then fails at the
                # moment somebody presses run.
                _upsert_model_spec_and_instance(
                    conn,
                    provider_key,
                    provider_spec_id,
                    config_id,
                    {
                        "model_name": em["modelName"],
                        "display_name": em.get("displayName", em["modelName"]),
                        "description": em.get("description", ""),
                        "context_window": em.get("contextWindow", 4096),
                        "input_cost_per_token": em.get("inputCostPerToken"),
                        "output_cost_per_token": em.get("outputCostPerToken"),
                    },
                    workspace_id,
                )
                model_count += 1

    return config_id, model_count


def _upsert_model_spec_and_instance(
    conn,
    provider_key: str,
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
        # Only our own rows are updated.
        #
        # uq_model_specs_provider_model is (provider_spec_id, model_name) without
        # workspace_id, so this lookup can return a spec a tenant created first for
        # the same model. Overwriting it would silently reprice their own usage and
        # rename it in their own list. The instance below simply points at it.
        #
        # COALESCE so a resource that omits a price leaves the existing one rather
        # than clearing it — unsetting a cost per token makes the model unrunnable,
        # which is a poor thing to do by leaving a field out.
        conn.execute(
            text(
                "UPDATE model_specs SET display_name = :dn, "
                "context_window = :cw, "
                "input_cost_per_token = COALESCE(:icpt, input_cost_per_token), "
                "output_cost_per_token = COALESCE(:ocpt, output_cost_per_token), "
                "updated_at = now() WHERE id = :id AND workspace_id = :ws"
            ),
            {
                "id": model_spec_id,
                "dn": model.get("display_name", model_name),
                "cw": model.get("context_window", 4096),
                "icpt": model.get("input_cost_per_token"),
                "ocpt": model.get("output_cost_per_token"),
                "ws": workspace_id,
            },
        )
    else:
        model_spec_id = str(uuid.uuid4())
        conn.execute(
            text(
                "INSERT INTO model_specs "
                "(id, provider_spec_id, model_name, display_name, description, "
                "context_window, input_cost_per_token, output_cost_per_token, "
                "is_active, workspace_id, created_by, "
                "created_at, updated_at) "
                "VALUES (:id, :spec_id, :mn, :dn, :desc, :cw, :icpt, :ocpt, true, "
                ":ws, :created_by, now(), now())"
            ),
            {
                "id": model_spec_id,
                "spec_id": provider_spec_id,
                "mn": model_name,
                "dn": model.get("display_name", model_name),
                "desc": model.get("description", ""),
                "cw": model.get("context_window", 4096),
                "icpt": model.get("input_cost_per_token"),
                "ocpt": model.get("output_cost_per_token"),
                "ws": workspace_id,
                "created_by": PLATFORM_PRINCIPAL_ID,
            },
        )

    _upsert_model_instance(
        conn, provider_key, config_id, model_spec_id, model_name, workspace_id
    )


def _upsert_model_instance(
    conn,
    provider_key: str,
    config_id: str,
    model_spec_id: str,
    model_name: str,
    workspace_id: str,
):
    """Create a ModelInstance if it doesn't already exist.

    The id is derived rather than generated for platform rows. It is what an agent
    stores when it selects this model and what billing's rate cards name, so a
    re-created row has to come back with the same id: a fresh one would silently
    unlink every agent using the model and match no rate card, which does not fail
    — it runs on our provider credit and charges nobody.
    """
    instance_id = (
        platform_instance_id(provider_key, model_name)
        if workspace_id == PLATFORM_WORKSPACE_ID
        else str(uuid.uuid4())
    )
    existing = conn.execute(
        text(
            "SELECT id FROM model_instances "
            "WHERE id = :id OR (provider_config_id = :cid AND model_spec_id = :msid)"
        ),
        {"id": instance_id, "cid": config_id, "msid": model_spec_id},
    ).fetchone()

    if not existing:
        conn.execute(
            text(
                "INSERT INTO model_instances "
                "(id, provider_config_id, model_spec_id, name, "
                "is_active, is_public, workspace_id, created_by, "
                "created_at, updated_at) "
                "VALUES (:id, :cid, :msid, :name, true, true, "
                ":ws, :created_by, now(), now())"
            ),
            {
                "id": instance_id,
                "cid": config_id,
                "msid": model_spec_id,
                "name": model_name,
                "ws": workspace_id,
                "created_by": PLATFORM_PRINCIPAL_ID,
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
    except kopf.PermanentError as e:
        # Record why before giving up. A permanent failure is the one kind nothing
        # retries, so if it does not reach the resource's status it reaches nobody:
        # the phase stays at whatever it was, the GitOps application still reports
        # healthy, and the model is simply missing from the picker with no evidence
        # anywhere that it was refused.
        patch.status["phase"] = "Error"
        patch.status["message"] = str(e)
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


# There is deliberately no delete handler.
#
# There was one, and it deactivated the configuration when the custom resource went
# away. That makes the disappearance of a file from git indistinguishable from a
# decision to stop selling a model: an Argo CD prune during a bad sync, a rename, a
# refactor of the directory — and the model goes dark for every paying workspace at
# once. This cluster has had that class of outage before, from a certificate
# reference that took TLS down for a week.
#
# Withdrawing a model is a decision and should be made deliberately, not inferred
# from an absence. The rows also outlive the resource on purpose: rate cards and
# usage records in the payments database reference the model instance id, and a
# disputed invoice six months from now is answered by rows that are still there.
#
# Its absence has a second effect worth knowing: kopf only installs finalizers for
# resources it has delete handlers for, so `kubectl delete` on one of these returns
# immediately instead of blocking until this process acknowledges it.


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


# ─── RegistrySync handlers ───────────────────────────────────────────────


def _read_configmap(namespace: str, name: str, key: str) -> str:
    v1 = k8s_client.CoreV1Api()
    cm = v1.read_namespaced_config_map(name=name, namespace=namespace)
    data = cm.data or {}
    if key not in data:
        raise kopf.PermanentError(f"Key '{key}' not found in ConfigMap '{name}'")
    return data[key]


def _resolve_source(spec: dict, namespace: str) -> tuple[str, str, str | None]:
    """Return (source_type, location_or_empty, configmap_body)."""
    source = spec.get("source") or {}
    source_type = source.get("type")
    if source_type == "url":
        url = source.get("url")
        if not url:
            raise kopf.PermanentError("source.url required when source.type=url")
        return "url", url, None
    if source_type == "file":
        path = source.get("url")
        if not path:
            raise kopf.PermanentError("source.url required when source.type=file")
        return "file", path, None
    if source_type == "configMap":
        ref = source.get("configMapRef") or {}
        cm_name = ref.get("name")
        cm_key = ref.get("key")
        if not cm_name or not cm_key:
            raise kopf.PermanentError(
                "configMapRef.name and configMapRef.key required when source.type=configMap"
            )
        body = _read_configmap(namespace, cm_name, cm_key)
        return "configMap", f"configMap:{cm_name}/{cm_key}", body
    raise kopf.PermanentError(f"Unknown source.type: {source_type}")


def _sync_registrysync(spec: dict, cr_name: str, namespace: str) -> dict:
    from registry_sync import reconcile as rs_reconcile

    registry_type = spec["type"]
    workspace_id = spec.get("workspaceId", PLATFORM_WORKSPACE_ID)
    source_type, location, configmap_body = _resolve_source(spec, namespace)
    with engine.begin() as conn:
        return rs_reconcile(
            conn,
            cr_name=cr_name,
            registry_type=registry_type,
            source_type=source_type,
            source_location=location,
            configmap_body=configmap_body,
            workspace_id=workspace_id,
        )


@kopf.on.create("agentarea.io", "v1alpha1", "registrysyncs")
@kopf.on.update("agentarea.io", "v1alpha1", "registrysyncs")
def on_registry_sync_change(spec, meta, namespace, patch, **_):
    cr_name = meta["name"]
    logger.info("Syncing RegistrySync %s/%s (type=%s)", namespace, cr_name, spec.get("type"))
    patch.status["phase"] = "Syncing"

    try:
        stats = _sync_registrysync(spec, cr_name, namespace)
    except kopf.PermanentError:
        patch.status["phase"] = "Error"
        raise
    except Exception as e:
        logger.exception("RegistrySync failed for %s/%s", namespace, cr_name)
        patch.status["phase"] = "Error"
        patch.status["message"] = str(e)
        raise kopf.TemporaryError(str(e), delay=60)

    patch.status["phase"] = "Synced"
    patch.status["lastSyncedAt"] = datetime.now(timezone.utc).isoformat()
    patch.status["itemCount"] = stats["total"]
    patch.status["newItems"] = stats["new"]
    patch.status["updatedItems"] = stats["updated"]
    patch.status["message"] = (
        f"Synced {stats['total']} items ({stats['new']} new, {stats['updated']} updated)"
    )
    logger.info(
        "RegistrySync %s/%s synced: total=%d new=%d updated=%d",
        namespace,
        cr_name,
        stats["total"],
        stats["new"],
        stats["updated"],
    )


@kopf.on.delete("agentarea.io", "v1alpha1", "registrysyncs")
def on_registry_sync_delete(spec, meta, namespace, **_):
    """Delete the `registries` row and let ON DELETE CASCADE drop registry_items.

    Installed entities are retained (additive-only); removing a RegistrySync CR
    stops future reconciliation but does not yank catalog entries users depend on.
    """
    cr_name = meta["name"]
    workspace_id = spec.get("workspaceId", PLATFORM_WORKSPACE_ID)
    logger.info("Deleting RegistrySync %s/%s", namespace, cr_name)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM registries WHERE name = :name AND workspace_id = :ws"
                ),
                {"name": cr_name, "ws": workspace_id},
            )
    except Exception as e:
        logger.error("Failed to delete registry %s: %s", cr_name, e)


@kopf.on.timer(
    "agentarea.io",
    "v1alpha1",
    "registrysyncs",
    interval=60,
    idle=60,
)
def registry_sync_timer(spec, meta, namespace, patch, status, **_):
    """Periodic resync driven by spec.syncIntervalSeconds (default 6h).

    kopf's timer fires every 60s (cheap: the body skips out quickly when the
    per-CR interval hasn't elapsed).
    """
    cr_name = meta["name"]
    interval = int(spec.get("syncIntervalSeconds", 21600))

    last_iso = (status or {}).get("lastSyncedAt")
    if last_iso:
        try:
            last = datetime.fromisoformat(last_iso.replace("Z", "+00:00"))
        except ValueError:
            last = None
        if last and (datetime.now(timezone.utc) - last).total_seconds() < interval:
            return

    try:
        stats = _sync_registrysync(spec, cr_name, namespace)
    except Exception as e:
        logger.exception("Timer resync failed for %s/%s", namespace, cr_name)
        patch.status["phase"] = "Error"
        patch.status["message"] = f"Resync failed: {e}"
        return

    patch.status["phase"] = "Synced"
    patch.status["lastSyncedAt"] = datetime.now(timezone.utc).isoformat()
    patch.status["itemCount"] = stats["total"]
    patch.status["newItems"] = stats["new"]
    patch.status["updatedItems"] = stats["updated"]
    patch.status["message"] = (
        f"Resynced {stats['total']} items ({stats['new']} new, {stats['updated']} updated)"
    )
