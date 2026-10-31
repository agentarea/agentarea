"""AgentArea K8s Operator — syncs LLMProviderConfig CRDs to the database.

Also reconciles PlatformConnection resources into a platform-managed MCP server
or OpenAPI connection and its bearer-token secret (see the PlatformConnection
section below).

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
    AGENTAREA_SECRET_ENCRYPTION_KEY    – Fernet key, same one the platform uses
    WATCH_NAMESPACE                  – Namespace to watch (default: all)
"""

import json
import logging
import os
import re
import unicodedata
import uuid
from datetime import datetime, timezone

import httpx
import kopf
import yaml
from cryptography.fernet import Fernet, InvalidToken
from kubernetes import client as k8s_client
from sqlalchemy import URL, create_engine, text

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

DATABASE_URL = URL.create(
    "postgresql+psycopg2",
    username=os.environ["AGENTAREA_DB_USER"],
    password=os.environ["AGENTAREA_DB_PASSWORD"],
    host=os.environ["AGENTAREA_DB_HOST"],
    port=int(os.environ.get("AGENTAREA_DB_PORT", "5432")),
    database=os.environ["AGENTAREA_DB_NAME"],
    query={"sslmode": os.environ["AGENTAREA_DB_SSLMODE"]}
    if os.environ.get("AGENTAREA_DB_SSLMODE")
    else {},
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
ENCRYPTION_KEY = os.environ.get("AGENTAREA_SECRET_ENCRYPTION_KEY", "")


def platform_config_id(provider_key: str) -> str:
    return str(uuid.uuid5(PLATFORM_ID_NAMESPACE, f"provider_config:{provider_key}"))


def platform_instance_id(provider_key: str, model_name: str) -> str:
    return str(uuid.uuid5(PLATFORM_ID_NAMESPACE, f"model_instance:{provider_key}:{model_name}"))


# Agents and clients attach the instance id, so it is derived from the
# connection's name for the same reason a model's is: a re-created row has to come
# back under the id everything already points at.
def platform_mcp_server_id(name: str) -> str:
    return str(uuid.uuid5(PLATFORM_ID_NAMESPACE, f"mcp_server:{name}"))


def platform_mcp_instance_id(name: str) -> str:
    return str(uuid.uuid5(PLATFORM_ID_NAMESPACE, f"mcp_instance:{name}"))


def platform_openapi_connection_id(name: str) -> str:
    return str(uuid.uuid5(PLATFORM_ID_NAMESPACE, f"openapi_connection:{name}"))


# MCP instances bind an exit by id in json_spec.egress_exit, so it is derived from
# the name like a connection's.
def platform_egress_exit_id(name: str) -> str:
    return str(uuid.uuid5(PLATFORM_ID_NAMESPACE, f"egress_exit:{name}"))


# Workspace-scoped resources (``spec.workspaceId`` set) get derived ids too, for
# the same reason as platform ones: every reconcile — create, update, the hourly
# rediscovery timer, an operator restart — has to land on the rows the previous
# one wrote. A generated id found nothing to update and inserted a fresh
# configuration, encrypted secret and model instances each time.
#
# They are keyed on the resource rather than on the provider alone, because a
# workspace may declare several configurations for one provider, and on the
# provider key as well, because a configuration is bound to its provider spec:
# pointing a resource at a different provider is a different configuration, not a
# rewrite of this one under its existing model instances.
#
# A separate namespace from the platform's, so nothing here can collide with a
# platform id. Freeze it and the name formats: changing either orphans every
# workspace configuration the operator has written and duplicates it on the next
# reconcile.
WORKSPACE_ID_NAMESPACE = uuid.UUID("3c9e2f71-4b8a-5d06-a1e7-9f2c6b0d4e85")


def workspace_config_id(
    workspace_id: str, namespace: str, cr_name: str, provider_key: str
) -> str:
    return str(
        uuid.uuid5(
            WORKSPACE_ID_NAMESPACE,
            f"provider_config:{workspace_id}:{namespace}/{cr_name}:{provider_key}",
        )
    )


def workspace_instance_id(config_id: str, model_name: str) -> str:
    return str(uuid.uuid5(WORKSPACE_ID_NAMESPACE, f"model_instance:{config_id}:{model_name}"))


def secret_name_for(config_id: str) -> str:
    """The name a configuration's key is stored under.

    ``provider_config_<uuid>`` is a reserved prefix: ``validate_user_secret_name``
    refuses it, and ``parse_managed_name`` reads it back into the owner, which is
    what stops the secrets API offering the row for editing or deletion. Naming it
    anything else would produce a secret a user could claim and overwrite.
    """
    return f"provider_config_{config_id}"


def store_api_key(conn, workspace_id: str, secret_name: str, api_key: str) -> str:
    """Encrypt the key into the workspace's secret store, creating or rotating it.

    Returns the secret's id, which the caller stores on the configuration. The name
    alone is what the runtime resolves through, but the id is the foreign key that
    stops the secret being deleted out from under a live configuration.

    Deliberately not stored on ``provider_configs.api_key``, which holds the *name*
    of a secret and is passed to the secret manager as one. Writing the key there
    would put a live credential in plain text in a column every workspace can read
    — the configuration is visible to all of them by design — and the lookup would
    then fail anyway, because no secret exists under a name that is itself a key.
    """
    return store_secret(
        conn,
        workspace_id,
        secret_name,
        api_key,
        owner_type="provider_config",
        owner_id=secret_name.removeprefix("provider_config_"),
    )


def store_secret(
    conn, workspace_id: str, secret_name: str, value: str, *, owner_type: str, owner_id: str
) -> str:
    """Encrypt ``value`` into the workspace's secret store; returns the row's id.

    A value that already decrypts to the same thing is left alone: Fernet output
    differs on every call, so an unconditional write would rewrite the row on
    every reconcile.
    """
    if not ENCRYPTION_KEY:
        raise kopf.PermanentError(
            "AGENTAREA_SECRET_ENCRYPTION_KEY is not set; refusing to write a "
            "credential that cannot be stored. Set it to the same Fernet key the "
            "platform API uses."
        )
    fernet = Fernet(ENCRYPTION_KEY.encode("utf-8"))
    existing = conn.execute(
        text(
            "SELECT id, encrypted_value FROM encrypted_secrets "
            "WHERE workspace_id = :ws AND secret_name = :name"
        ),
        {"ws": workspace_id, "name": secret_name},
    ).fetchone()
    if existing is not None and existing[1] is not None:
        try:
            current = fernet.decrypt(existing[1].encode("utf-8")).decode("utf-8")
        except InvalidToken:
            logger.warning(
                "Secret %s in workspace %s does not decrypt with the current key; "
                "rewriting it",
                secret_name,
                workspace_id,
            )
            current = None
        if current == value:
            return str(existing[0])
    encrypted = fernet.encrypt(value.encode("utf-8")).decode()
    # RETURNING on the DO UPDATE branch gives the existing row's id, not the one
    # generated above and discarded — which is what makes this safe to call on
    # every reconcile.
    row = conn.execute(
        text(
            "INSERT INTO encrypted_secrets "
            "(id, workspace_id, secret_name, encrypted_value, owner_type, owner_id, "
            "created_by, created_at, updated_at) "
            "VALUES (:id, :ws, :name, :val, :owner_type, :owner, :by, now(), now()) "
            "ON CONFLICT (workspace_id, secret_name) DO UPDATE SET "
            "encrypted_value = EXCLUDED.encrypted_value, external_ref = NULL, "
            "updated_by = EXCLUDED.created_by, updated_at = now() "
            "RETURNING id"
        ),
        {
            "id": str(uuid.uuid4()),
            "ws": workspace_id,
            "name": secret_name,
            "val": encrypted,
            "owner_type": owner_type,
            "owner": owner_id,
            "by": PLATFORM_PRINCIPAL_ID,
        },
    ).fetchone()
    return str(row[0])


def _cross_namespace_secret_ref_error(
    secret_ref: dict, namespace: str, field: str = "apiKeySecretRef"
) -> str | None:
    """Return an error message if the ref names a namespace other than the CR's own.

    ``apiKeySecretRef`` only ever resolves in the CR's own namespace, and the
    operator's Secrets RBAC is scoped there for the same reason: reading a
    Secret on a CR author's behalf into a namespace they may not themselves
    have Secrets access to is a confused-deputy read, not a legitimate use
    case. A mismatched ``namespace`` fails loudly here rather than being
    silently narrowed to the CR's own namespace.
    """
    ref_namespace = secret_ref.get("namespace")
    if ref_namespace and ref_namespace != namespace:
        return (
            f"{field}.namespace '{ref_namespace}' does not match this "
            f"resource's own namespace '{namespace}'; cross-namespace secret "
            "references are not allowed"
        )
    return None


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
    *,
    namespace: str,
) -> tuple[str, int]:
    """Sync a ProviderConfig + optional models to the database.

    ``namespace`` and ``cr_name`` identify the custom resource; a workspace-scoped
    configuration's id is derived from them, so reconciling the same resource
    again updates the rows it wrote rather than adding new ones.

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
        #
        # Derived for workspace-scoped resources as well, from the resource's own
        # identity: a generated id there meant every reconcile inserted another
        # configuration, secret and set of model instances (#708).
        is_platform = workspace_id == PLATFORM_WORKSPACE_ID
        config_id = (
            platform_config_id(provider_key)
            if is_platform
            else workspace_config_id(workspace_id, namespace, cr_name, provider_key)
        )
        managed_by = MANAGED_BY_PLATFORM if is_platform else None

        existing = conn.execute(
            text("SELECT id FROM provider_configs WHERE id = :id"),
            {"id": config_id},
        ).fetchone()

        # The configuration stores the NAME of a secret; the key itself goes to the
        # secret store under that name, in the same transaction.
        secret_name = secret_name_for(config_id)
        secret_id = store_api_key(conn, workspace_id, secret_name, api_key)

        if existing:
            conn.execute(
                text(
                    "UPDATE provider_configs SET "
                    "name = :name, api_key = :key, api_key_secret_id = :secret_id, "
                    "endpoint_url = :url, managed_by = :managed_by, "
                    "is_active = true, is_public = :pub, updated_at = now() "
                    "WHERE id = :id"
                ),
                {
                    "id": config_id,
                    "name": name,
                    "key": secret_name,
                    "secret_id": secret_id,
                    "url": endpoint_url,
                    "managed_by": managed_by,
                    "pub": is_public,
                },
            )
        else:
            # Every column here exists on provider_configs, which is less obvious
            # than it sounds: this statement carried a `source` column for as long
            # as it has existed and no schema has ever had one. It never showed,
            # because the operator was failing earlier on permissions and never
            # reached the insert. Raw SQL against a table whose model lives in
            # another repository is a standing invitation to this; the test below
            # runs it against a real Postgres for that reason.
            conn.execute(
                text(
                    "INSERT INTO provider_configs "
                    "(id, provider_spec_id, name, api_key, api_key_secret_id, "
                    "endpoint_url, managed_by, is_active, is_public, "
                    "workspace_id, created_by, created_at, updated_at) "
                    "VALUES (:id, :spec_id, :name, :key, :secret_id, :url, "
                    ":managed_by, true, :pub, :ws, :created_by, now(), now())"
                ),
                {
                    "id": config_id,
                    "spec_id": provider_spec_id,
                    "name": name,
                    "key": secret_name,
                    "secret_id": secret_id,
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
                        # Unset means the platform holds no output cap of its own
                        # for the model; the policy's per-call ceiling still applies.
                        "max_output_tokens": em.get("maxOutputTokens"),
                        "supports_vision": em.get("supportsVision", False),
                        "supports_reasoning": em.get("supportsReasoning", False),
                        "reasoning_efforts": em.get("reasoningEfforts"),
                        "input_cost_per_token": em.get("inputCostPerToken"),
                        "output_cost_per_token": em.get("outputCostPerToken"),
                        "cached_input_cost_per_token": em.get("cachedInputCostPerToken"),
                        "cache_creation_input_cost_per_token": em.get(
                            "cacheCreationInputCostPerToken"
                        ),
                        # Always written, an omitted list as []: the resource is
                        # the whole truth about a model's tags, so taking
                        # "default" off in git takes it off the model.
                        "tags": em.get("tags", []),
                    },
                    workspace_id,
                )
                model_count += 1

    return config_id, model_count


def _json_or_none(value: object) -> str | None:
    return None if value is None else json.dumps(value)


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
            "WHERE provider_spec_id = :spec_id AND model_name = :mn "
            "AND workspace_id = :ws"
        ),
        {"spec_id": provider_spec_id, "mn": model_name, "ws": workspace_id},
    ).fetchone()

    if ms_row:
        model_spec_id = str(ms_row[0])
        # Only our own rows are updated, and the lookup only finds our own:
        # uq_model_specs_workspace_provider_model is per workspace, so a tenant's
        # spec for the same model is theirs to price, and ours is not theirs.
        #
        # COALESCE so a resource that omits a price leaves the existing one rather
        # than clearing it — unsetting a cost per token makes the model unrunnable,
        # which is a poor thing to do by leaving a field out.
        conn.execute(
            text(
                "UPDATE model_specs SET display_name = :dn, "
                "context_window = :cw, "
                "max_output_tokens = :mot, "
                "supports_vision = COALESCE(:sv, supports_vision), "
                "supports_reasoning = COALESCE(:sr, supports_reasoning), "
                "reasoning_efforts = COALESCE(CAST(:re AS jsonb), reasoning_efforts), "
                "input_cost_per_token = COALESCE(:icpt, input_cost_per_token), "
                "output_cost_per_token = COALESCE(:ocpt, output_cost_per_token), "
                "cached_input_cost_per_token = COALESCE(:cicpt, cached_input_cost_per_token), "
                "cache_creation_input_cost_per_token = "
                "COALESCE(:ccicpt, cache_creation_input_cost_per_token), "
                "updated_at = now() WHERE id = :id AND workspace_id = :ws"
            ),
            {
                "id": model_spec_id,
                "dn": model.get("display_name", model_name),
                "cw": model.get("context_window", 4096),
                "mot": model.get("max_output_tokens"),
                "sv": model.get("supports_vision"),
                "sr": model.get("supports_reasoning"),
                "re": _json_or_none(model.get("reasoning_efforts")),
                "icpt": model.get("input_cost_per_token"),
                "ocpt": model.get("output_cost_per_token"),
                "cicpt": model.get("cached_input_cost_per_token"),
                "ccicpt": model.get("cache_creation_input_cost_per_token"),
                "ws": workspace_id,
            },
        )
    else:
        model_spec_id = str(uuid.uuid4())
        conn.execute(
            text(
                "INSERT INTO model_specs "
                "(id, provider_spec_id, model_name, display_name, description, "
                "context_window, max_output_tokens, supports_vision, supports_reasoning, "
                "reasoning_efforts, input_cost_per_token, output_cost_per_token, "
                "cached_input_cost_per_token, cache_creation_input_cost_per_token, "
                "is_active, workspace_id, created_by, "
                "created_at, updated_at) "
                "VALUES (:id, :spec_id, :mn, :dn, :desc, :cw, :mot, "
                "COALESCE(:sv, false), COALESCE(:sr, false), CAST(:re AS jsonb), :icpt, :ocpt, :cicpt, :ccicpt, "
                "true, :ws, :created_by, now(), now())"
            ),
            {
                "id": model_spec_id,
                "spec_id": provider_spec_id,
                "mn": model_name,
                "dn": model.get("display_name", model_name),
                "desc": model.get("description", ""),
                "cw": model.get("context_window", 4096),
                "mot": model.get("max_output_tokens"),
                "sv": model.get("supports_vision"),
                "sr": model.get("supports_reasoning"),
                "re": _json_or_none(model.get("reasoning_efforts")),
                "icpt": model.get("input_cost_per_token"),
                "ocpt": model.get("output_cost_per_token"),
                "cicpt": model.get("cached_input_cost_per_token"),
                "ccicpt": model.get("cache_creation_input_cost_per_token"),
                "ws": workspace_id,
                "created_by": PLATFORM_PRINCIPAL_ID,
            },
        )

    _upsert_model_instance(
        conn,
        provider_key,
        config_id,
        model_spec_id,
        model_name,
        workspace_id,
        model.get("tags"),
    )


def _upsert_model_instance(
    conn,
    provider_key: str,
    config_id: str,
    model_spec_id: str,
    model_name: str,
    workspace_id: str,
    tags: list[str] | None = None,
):
    """Create a ModelInstance if it doesn't already exist, and set its tags.

    The id is derived rather than generated. For platform rows it is what an agent
    stores when it selects this model and what billing's rate cards name, so a
    re-created row has to come back with the same id: a fresh one would silently
    unlink every agent using the model and match no rate card, which does not fail
    — it runs on our provider credit and charges nobody. Workspace rows derive it
    from their (already derived) configuration id, so a reconcile finds the row it
    wrote last time instead of inserting another.

    ``tags`` of None leaves an existing row's tags alone: discovered models have
    no resource entry to take them from. A list, empty included, replaces them.
    The tags are how the webapp picks the model a new agent starts on
    (``default``), which is why they live here rather than in its configuration.
    """
    instance_id = (
        platform_instance_id(provider_key, model_name)
        if workspace_id == PLATFORM_WORKSPACE_ID
        else workspace_instance_id(config_id, model_name)
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
                "is_active, is_public, tags, workspace_id, created_by, "
                "created_at, updated_at) "
                "VALUES (:id, :cid, :msid, :name, true, true, CAST(:tags AS JSONB), "
                ":ws, :created_by, now(), now())"
            ),
            {
                "id": instance_id,
                "cid": config_id,
                "msid": model_spec_id,
                "name": model_name,
                "tags": json.dumps(tags or []),
                "ws": workspace_id,
                "created_by": PLATFORM_PRINCIPAL_ID,
            },
        )
    elif tags is not None:
        conn.execute(
            text(
                "UPDATE model_instances SET tags = CAST(:tags AS JSONB), "
                "updated_at = now() WHERE id = :id AND workspace_id = :ws"
            ),
            {"id": existing[0], "tags": json.dumps(tags), "ws": workspace_id},
        )


def platform_default_models() -> list[str]:
    """model_name of every active platform model tagged ``default``, by name.

    The webapp starts a new agent on the first of these, so more than one is not
    an error, but it is almost certainly a mistake: the default is whichever sorts
    first, not the one somebody meant. Across all resources, because each
    resource only knows its own models.
    """
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT ms.model_name FROM model_instances mi "
                "JOIN provider_configs pc ON pc.id = mi.provider_config_id "
                "JOIN model_specs ms ON ms.id = mi.model_spec_id "
                "WHERE pc.managed_by = :managed_by AND mi.is_active "
                "AND mi.tags @> CAST(:tag AS JSONB) ORDER BY ms.model_name"
            ),
            {"managed_by": MANAGED_BY_PLATFORM, "tag": json.dumps(["default"])},
        ).fetchall()
    return [row[0] for row in rows]


def default_tag_warning(defaults: list[str]) -> str | None:
    """What to say when the ``default`` tag is on more than one platform model."""
    if len(defaults) <= 1:
        return None
    return (
        f"{len(defaults)} platform models are tagged default "
        f"({', '.join(defaults)}); new agents start on {defaults[0]}. Tag exactly one."
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

    ns_error = _cross_namespace_secret_ref_error(secret_ref, namespace)
    if ns_error:
        patch.status["phase"] = "Error"
        patch.status["message"] = ns_error
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
        config_id, model_count = sync_provider_config(
            spec, api_key, cr_name, namespace=namespace
        )
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
    warning = default_tag_warning(platform_default_models())
    if warning:
        logger.warning("LLMProviderConfig %s/%s: %s", namespace, cr_name, warning)
        patch.status["message"] += f"; warning: {warning}"
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

    ns_error = _cross_namespace_secret_ref_error(secret_ref, namespace)
    if ns_error:
        patch.status["phase"] = "Error"
        patch.status["message"] = ns_error
        return

    try:
        api_key = read_secret(namespace, secret_ref["name"], secret_ref["key"])
        config_id, model_count = sync_provider_config(
            spec, api_key, cr_name, namespace=namespace
        )
        patch.status["phase"] = "Synced"
        patch.status["discoveredModels"] = model_count
        patch.status["lastSyncedAt"] = datetime.now(timezone.utc).isoformat()
        patch.status["message"] = f"Re-synced with {model_count} models"
    except Exception as e:
        logger.error("Periodic rediscovery failed for %s: %s", cr_name, e)
        patch.status["message"] = f"Rediscovery failed: {e}"


# ─── PlatformConnection ──────────────────────────────────────────────────
#
# The same offer as a platform LLM provider, for one tool connection: a
# connection every workspace can attach, on a credential only the platform
# holds. ``transport: mcp`` writes an MCP server spec and instance,
# ``transport: openapi`` an OpenAPI connection; either way the bearer token goes
# to the platform workspace's secret store under the name the runtime resolves
# the connection's Authorization header from. A ``catalogId`` names the catalog
# entry the connection is an instance of, which is where its cost model lives.

MCP_AUTH_ENV_VAR = "Authorization"
OPENAPI_AUTH_HEADER = "Authorization"

# A catalog entry that is missing now usually arrives with the next catalog sync.
CATALOG_RETRY_DELAY = 600

# Keep in sync with agentarea_mcp.domain.verification_types.DEFAULT_VERIFICATION.
NEVER_ATTEMPTED_VERIFICATION = {
    "schema_version": 1,
    "status": "never_attempted",
    "at": None,
    "error": None,
}


def mcp_secret_name_for(instance_id: str) -> str:
    """``mcp_instance_{id}_{ENV}``: the reserved name MCPEnvironmentService reads."""
    return f"mcp_instance_{instance_id}_{MCP_AUTH_ENV_VAR}"


def openapi_secret_name_for(connection_id: str) -> str:
    """``openapi:{id}:header:{name}``: the reserved name OpenAPIConnectionService reads."""
    return f"openapi:{connection_id}:header:{OPENAPI_AUTH_HEADER}"


def catalog_item(conn, catalog_id: str) -> tuple[str, dict]:
    """The active catalog entry ``catalog_id`` names, preferred registry first."""
    row = conn.execute(
        text(
            "SELECT id, spec FROM registry_items "
            "WHERE external_id = :ext AND registry_active "
            "ORDER BY registry_priority, id LIMIT 1"
        ),
        {"ext": catalog_id},
    ).fetchone()
    if row is None:
        raise kopf.TemporaryError(
            f"Catalog item '{catalog_id}' not found (catalog not synced yet?)",
            delay=CATALOG_RETRY_DELAY,
        )
    return str(row[0]), row[1] or {}


def _generate_slug(name: str) -> str:
    """ASCII, lowercase, hyphenated slug, as agentarea_common.utils.slug.generate_slug."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    if len(slug) > 100:
        slug = slug[:100].rstrip("-")
    return slug or "item"


def _unique_mcp_slug(conn, workspace_id: str, name: str) -> str:
    base = _generate_slug(name)

    def _taken(candidate: str) -> bool:
        return (
            conn.execute(
                text(
                    "SELECT 1 FROM mcp_servers WHERE workspace_id = :ws AND slug = :slug LIMIT 1"
                ),
                {"ws": workspace_id, "slug": candidate},
            ).fetchone()
            is not None
        )

    if not _taken(base):
        return base
    for suffix in range(2, 1000):
        candidate = f"{base}-{suffix}"
        if not _taken(candidate):
            return candidate
    raise ValueError(f"Exhausted collision suffixes (-2..-999) for slug base '{base}'")


def sync_mcp_connection(spec: dict, token: str) -> tuple[str, str]:
    """Upsert the server spec, instance and token secret. Returns their two ids.

    Re-running with the same spec changes no row. A changed endpoint or transport
    resets the instance's verification and tool snapshot, so the platform
    re-verifies it against the new server instead of trusting the old one's.
    """
    name = spec["name"]
    description = spec.get("description") or ""
    endpoint_url = spec["endpointUrl"]
    transport = spec.get("mcpTransport") or "streamable-http"
    catalog_id = spec.get("catalogId")
    server_id = platform_mcp_server_id(name)
    instance_id = platform_mcp_instance_id(name)
    remotes = [{"type": transport, "url": endpoint_url}]
    instance_json_spec = {"env_vars": [MCP_AUTH_ENV_VAR]}

    with engine.begin() as conn:
        if catalog_id:
            _, item_spec = catalog_item(conn, catalog_id)
            raw_spec = item_spec.get("raw_spec") or {}
            server_json_spec = {
                "name": catalog_id,
                "metadata": raw_spec.get("metadata") or {},
                "remotes": remotes,
            }
        else:
            server_json_spec = {"remotes": remotes}

        server = conn.execute(
            text("SELECT remote_url, json_spec FROM mcp_servers WHERE id = :id"),
            {"id": server_id},
        ).fetchone()
        endpoint_changed = server is not None and (
            server[0] != endpoint_url or (server[1] or {}).get("remotes") != remotes
        )

        server_params = {
            "id": server_id,
            "desc": description,
            "rurl": endpoint_url,
            "json_spec": json.dumps(server_json_spec),
            "ws": PLATFORM_WORKSPACE_ID,
        }
        if server is None:
            conn.execute(
                text(
                    "INSERT INTO mcp_servers (id, name, slug, description, version, tags, "
                    "status, is_public, env_schema, remote_url, json_spec, "
                    "registry_item_id, workspace_id, created_by, created_at, updated_at) "
                    "VALUES (:id, :name, :slug, :desc, '1.0.0', CAST('[]' AS JSON), "
                    "'active', false, CAST('[]' AS JSON), :rurl, CAST(:json_spec AS JSONB), "
                    "NULL, :ws, :created_by, now(), now())"
                ),
                server_params
                | {
                    "name": name,
                    "slug": _unique_mcp_slug(conn, PLATFORM_WORKSPACE_ID, name),
                    "created_by": PLATFORM_PRINCIPAL_ID,
                },
            )
        else:
            conn.execute(
                text(
                    "UPDATE mcp_servers SET description = :desc, remote_url = :rurl, "
                    "json_spec = CAST(:json_spec AS JSONB), status = 'active', "
                    "updated_by = :by, updated_at = now() "
                    "WHERE id = :id AND workspace_id = :ws AND ("
                    "description, remote_url, json_spec, status) IS DISTINCT FROM "
                    "(:desc, :rurl, CAST(:json_spec AS JSONB), 'active')"
                ),
                server_params | {"by": PLATFORM_PRINCIPAL_ID},
            )

        instance = conn.execute(
            text("SELECT id FROM mcp_server_instances WHERE id = :id"),
            {"id": instance_id},
        ).fetchone()
        instance_params = {
            "id": instance_id,
            "server_spec_id": server_id,
            "name": name,
            "desc": description,
            "json_spec": json.dumps(instance_json_spec),
            "managed_by": MANAGED_BY_PLATFORM,
            "ws": PLATFORM_WORKSPACE_ID,
        }
        if instance is None:
            conn.execute(
                text(
                    "INSERT INTO mcp_server_instances (id, server_spec_id, name, "
                    "description, transport, json_spec, network_scope, managed_by, "
                    "workspace_id, created_by, created_at, updated_at) "
                    "VALUES (:id, :server_spec_id, :name, :desc, 'url', "
                    "CAST(:json_spec AS JSONB), 'private', :managed_by, :ws, "
                    ":created_by, now(), now())"
                ),
                instance_params | {"created_by": PLATFORM_PRINCIPAL_ID},
            )
        elif endpoint_changed:
            conn.execute(
                text(
                    "UPDATE mcp_server_instances SET server_spec_id = :server_spec_id, "
                    "name = :name, description = :desc, transport = 'url', "
                    "json_spec = CAST(:json_spec AS JSONB), managed_by = :managed_by, "
                    "verification = CAST(:verification AS JSONB), tools = NULL, "
                    "updated_at = now() WHERE id = :id AND workspace_id = :ws"
                ),
                instance_params
                | {"verification": json.dumps(NEVER_ATTEMPTED_VERIFICATION)},
            )
        else:
            conn.execute(
                text(
                    "UPDATE mcp_server_instances SET server_spec_id = :server_spec_id, "
                    "name = :name, description = :desc, transport = 'url', "
                    "json_spec = CAST(:json_spec AS JSONB), managed_by = :managed_by, "
                    "updated_at = now() WHERE id = :id AND workspace_id = :ws AND ("
                    "server_spec_id, name, description, transport, json_spec, managed_by"
                    ") IS DISTINCT FROM (:server_spec_id, :name, :desc, 'url', "
                    "CAST(:json_spec AS JSONB), :managed_by)"
                ),
                instance_params,
            )

        store_secret(
            conn,
            PLATFORM_WORKSPACE_ID,
            mcp_secret_name_for(instance_id),
            f"Bearer {token.strip()}",
            owner_type="mcp_instance",
            owner_id=instance_id,
        )

    return server_id, instance_id


class _SpecLoader(yaml.SafeLoader):
    """Keeps timestamps as text, so the spec stays JSON-serialisable."""


_SpecLoader.add_constructor("tag:yaml.org,2002:timestamp", _SpecLoader.construct_yaml_str)


def fetch_openapi_spec(spec_url: str) -> dict:
    """The OpenAPI 3.x document at ``spec_url``, JSON or YAML."""
    resp = httpx.get(spec_url, timeout=30)
    resp.raise_for_status()
    body = resp.text
    if spec_url.endswith((".yaml", ".yml")):
        document = yaml.load(body, Loader=_SpecLoader)  # noqa: S506 -- a SafeLoader subclass
    else:
        try:
            document = json.loads(body)
        except json.JSONDecodeError:
            document = yaml.load(body, Loader=_SpecLoader)  # noqa: S506
    if not isinstance(document, dict):
        raise ValueError(f"Spec at {spec_url} is not an object")
    version = document.get("openapi")
    if not isinstance(version, str) or not version.startswith("3."):
        raise ValueError(f"Spec at {spec_url} is not OpenAPI 3.x (openapi: {version!r})")
    return document


_OPENAPI_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


def _resolve_ref(obj, spec: dict, _seen: set[str] | None = None):
    if not isinstance(obj, dict) or "$ref" not in obj:
        return obj
    ref = obj["$ref"]
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return obj
    if _seen is None:
        _seen = set()
    if ref in _seen:
        return {}
    _seen.add(ref)
    resolved = spec
    for part in ref.lstrip("#/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(resolved, dict):
            return obj
        resolved = resolved.get(part)
        if resolved is None:
            return obj
    if isinstance(resolved, dict) and "$ref" in resolved:
        return _resolve_ref(resolved, spec, _seen)
    return resolved


def _generate_name(method: str, path: str) -> str:
    segments = [s for s in path.replace("{", "").replace("}", "").split("/") if s]
    return f"{method}_{'_'.join(segments)}"


# Mirrors agentarea_openapi.application.spec_parser.parse_openapi_spec.
def openapi_tools(spec: dict) -> list[dict]:
    """The ``available_tools`` projection of an OpenAPI spec: name, description, inputSchema."""
    tools: list[dict] = []
    for path, path_item in (spec.get("paths") or {}).items():
        if not path_item or not isinstance(path_item, dict):
            continue
        path_params = [_resolve_ref(p, spec) for p in path_item.get("parameters") or []]
        for method in _OPENAPI_METHODS:
            if method not in path_item:
                continue
            operation = path_item[method]
            merged: dict[tuple[str, str], dict] = {}
            op_params = [_resolve_ref(p, spec) for p in operation.get("parameters") or []]
            for param in path_params + op_params:
                merged[(param.get("name", ""), param.get("in", ""))] = param

            properties: dict = {}
            required: list[str] = []
            for param in merged.values():
                param_name = param.get("name", "")
                if not param_name:
                    continue
                properties[param_name] = _resolve_ref(
                    param.get("schema", {"type": "string"}), spec
                )
                if param.get("required", False):
                    required.append(param_name)

            raw_body = operation.get("requestBody")
            if raw_body:
                body = _resolve_ref(raw_body, spec)
                content = body.get("content") or {}
                if "application/json" in content:
                    body_schema = _resolve_ref(
                        content["application/json"].get("schema", {}), spec
                    )
                    if body_schema:
                        properties["body"] = body_schema
                        if body.get("required", True):
                            required.append("body")

            tools.append(
                {
                    "name": operation.get("operationId") or _generate_name(method, path),
                    "description": operation.get("summary")
                    or operation.get("description")
                    or "",
                    "inputSchema": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                }
            )
    return tools


def sync_openapi_connection(spec: dict, token: str) -> str:
    """Upsert the OpenAPI connection and its token secret. Returns the connection id.

    The spec is fetched from the catalog entry's ``spec_url`` on every reconcile,
    outside the write transaction; re-running against an unchanged spec changes
    no row.
    """
    name = spec["name"]
    catalog_id = spec.get("catalogId")
    if not catalog_id:
        raise kopf.PermanentError("catalogId is required when transport is openapi")
    connection_id = platform_openapi_connection_id(name)

    with engine.begin() as conn:
        item_id, item_spec = catalog_item(conn, catalog_id)
    spec_url = item_spec.get("spec_url")
    if not spec_url:
        raise kopf.TemporaryError(
            f"Catalog item '{catalog_id}' has no spec_url", delay=CATALOG_RETRY_DELAY
        )
    document = fetch_openapi_spec(spec_url)

    params = {
        "id": connection_id,
        "name": name,
        "desc": spec.get("description") or "",
        "spec_url": spec_url,
        "spec_content": json.dumps(document),
        "base_url": spec["endpointUrl"],
        "item_id": item_id,
        "tools": json.dumps(openapi_tools(document)),
        "headers": json.dumps([{"name": OPENAPI_AUTH_HEADER, "secret": True, "value": None}]),
        "managed_by": MANAGED_BY_PLATFORM,
        "ws": PLATFORM_WORKSPACE_ID,
    }
    with engine.begin() as conn:
        existing = conn.execute(
            text("SELECT id FROM openapi_connections WHERE id = :id"),
            {"id": connection_id},
        ).fetchone()
        if existing is None:
            conn.execute(
                text(
                    "INSERT INTO openapi_connections (id, name, description, spec_url, "
                    "spec_content, base_url, registry_item_id, available_tools, "
                    "custom_headers, allowed_auth_origins, status, managed_by, "
                    "workspace_id, created_by, created_at, updated_at) "
                    "VALUES (:id, :name, :desc, :spec_url, CAST(:spec_content AS JSONB), "
                    ":base_url, :item_id, CAST(:tools AS JSONB), CAST(:headers AS JSON), "
                    "NULL, 'active', :managed_by, :ws, :created_by, now(), now())"
                ),
                params | {"created_by": PLATFORM_PRINCIPAL_ID},
            )
        else:
            # custom_headers and allowed_auth_origins are json, which has no
            # equality operator; compared as jsonb.
            conn.execute(
                text(
                    "UPDATE openapi_connections SET name = :name, description = :desc, "
                    "spec_url = :spec_url, spec_content = CAST(:spec_content AS JSONB), "
                    "base_url = :base_url, registry_item_id = :item_id, "
                    "available_tools = CAST(:tools AS JSONB), "
                    "custom_headers = CAST(:headers AS JSON), allowed_auth_origins = NULL, "
                    "status = 'active', managed_by = :managed_by, updated_at = now() "
                    "WHERE id = :id AND workspace_id = :ws AND ("
                    "name, description, spec_url, spec_content, base_url, registry_item_id, "
                    "available_tools, CAST(custom_headers AS JSONB), "
                    "CAST(allowed_auth_origins AS JSONB), status, managed_by"
                    ") IS DISTINCT FROM (:name, :desc, :spec_url, "
                    "CAST(:spec_content AS JSONB), :base_url, CAST(:item_id AS UUID), "
                    "CAST(:tools AS JSONB), CAST(:headers AS JSONB), CAST(NULL AS JSONB), "
                    "'active', :managed_by)"
                ),
                params,
            )

        store_secret(
            conn,
            PLATFORM_WORKSPACE_ID,
            openapi_secret_name_for(connection_id),
            f"Bearer {token.strip()}",
            owner_type="openapi_connection",
            owner_id=connection_id,
        )

    return connection_id


def sync_platform_connection(spec: dict, token: str) -> tuple[str, str | None]:
    """Sync by transport. Returns (connection id, MCP server id or None)."""
    transport = spec.get("transport")
    if transport == "mcp":
        server_id, instance_id = sync_mcp_connection(spec, token)
        return instance_id, server_id
    if transport == "openapi":
        return sync_openapi_connection(spec, token), None
    raise kopf.PermanentError(f"Unknown transport: {transport!r}")


def _read_connection_token(spec: dict, namespace: str, patch) -> str | None:
    """The token, or None after recording why it could not be read."""
    secret_ref = spec.get("tokenSecretRef")
    if not secret_ref:
        patch.status["phase"] = "Error"
        patch.status["message"] = "tokenSecretRef is required"
        return None
    ns_error = _cross_namespace_secret_ref_error(secret_ref, namespace, "tokenSecretRef")
    if ns_error:
        patch.status["phase"] = "Error"
        patch.status["message"] = ns_error
        return None
    try:
        return read_secret(namespace, secret_ref["name"], secret_ref["key"])
    except Exception as e:
        patch.status["phase"] = "Error"
        patch.status["message"] = f"Failed to read secret: {e}"
        raise kopf.TemporaryError(str(e), delay=30) from e


def _record_connection_sync(
    patch, connection_id: str, server_id: str | None, message: str
) -> None:
    patch.status["phase"] = "Synced"
    patch.status["connectionId"] = connection_id
    # None removes the field, so a resource moved off mcp does not keep a stale id.
    patch.status["mcpServerId"] = server_id
    patch.status["lastSyncedAt"] = datetime.now(timezone.utc).isoformat()
    patch.status["message"] = message


@kopf.on.create("agentarea.io", "v1alpha1", "platformconnections")
@kopf.on.update("agentarea.io", "v1alpha1", "platformconnections")
def on_platform_connection_change(spec, meta, namespace, patch, **_):
    cr_name = meta["name"]
    logger.info(
        "Syncing PlatformConnection %s/%s (transport=%s)",
        namespace, cr_name, spec.get("transport"),
    )

    token = _read_connection_token(spec, namespace, patch)
    if token is None:
        return

    try:
        connection_id, server_id = sync_platform_connection(spec, token)
    except (kopf.PermanentError, kopf.TemporaryError) as e:
        patch.status["phase"] = "Error"
        patch.status["message"] = str(e)
        raise
    except Exception as e:
        logger.exception("PlatformConnection sync failed for %s/%s", namespace, cr_name)
        patch.status["phase"] = "Error"
        patch.status["message"] = str(e)
        raise kopf.TemporaryError(str(e), delay=60) from e

    _record_connection_sync(patch, connection_id, server_id, "Synced")
    logger.info(
        "Synced PlatformConnection %s/%s → connection=%s",
        namespace, cr_name, connection_id,
    )


# No delete handler, for the provider path's reasons: a resource vanishing from
# git is not a decision to withdraw a connection every workspace may be using.


@kopf.on.timer("agentarea.io", "v1alpha1", "platformconnections", interval=3600)
def periodic_platform_connection_resync(spec, meta, namespace, patch, **_):
    """Re-read the token hourly, so a rotated Secret reaches the platform."""
    cr_name = meta["name"]
    try:
        token = _read_connection_token(spec, namespace, patch)
        if token is None:
            return
        connection_id, server_id = sync_platform_connection(spec, token)
    except Exception as e:
        logger.exception("PlatformConnection resync failed for %s/%s", namespace, cr_name)
        patch.status["phase"] = "Error"
        patch.status["message"] = f"Resync failed: {e}"
        return
    _record_connection_sync(patch, connection_id, server_id, "Re-synced")


def sync_platform_egress_exit(spec: dict) -> str:
    """Upsert the platform exit every workspace may bind. Returns its id.

    A platform exit leaves through a hop of the egress proxy's own configuration;
    it holds no credentials. Re-running against an unchanged spec changes no row.
    """
    exit_id = platform_egress_exit_id(spec["name"])
    params = {
        "id": exit_id,
        "name": spec["name"],
        "desc": spec.get("description"),
        "via": spec["via"],
        "remote_dns": bool(spec.get("remoteDns", False)),
        "managed_by": MANAGED_BY_PLATFORM,
        "ws": PLATFORM_WORKSPACE_ID,
        "created_by": PLATFORM_PRINCIPAL_ID,
    }
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO egress_exits (id, name, description, via, remote_dns, "
                "allow_plaintext_credentials, managed_by, workspace_id, created_by, "
                "created_at, updated_at) "
                "VALUES (:id, :name, :desc, :via, :remote_dns, false, :managed_by, :ws, "
                ":created_by, now(), now()) "
                "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, "
                "description = EXCLUDED.description, via = EXCLUDED.via, "
                "remote_dns = EXCLUDED.remote_dns, updated_at = now() "
                "WHERE egress_exits.workspace_id = EXCLUDED.workspace_id AND ("
                "egress_exits.name, egress_exits.description, egress_exits.via, "
                "egress_exits.remote_dns"
                ") IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.description, EXCLUDED.via, "
                "EXCLUDED.remote_dns)"
            ),
            params,
        )
    return exit_id


@kopf.on.create("agentarea.io", "v1alpha1", "platformegressexits")
@kopf.on.update("agentarea.io", "v1alpha1", "platformegressexits")
def on_platform_egress_exit_change(spec, meta, namespace, patch, **_):
    cr_name = meta["name"]
    logger.info("Syncing PlatformEgressExit %s/%s (via=%s)", namespace, cr_name, spec.get("via"))
    try:
        exit_id = sync_platform_egress_exit(spec)
    except Exception as e:
        logger.exception("PlatformEgressExit sync failed for %s/%s", namespace, cr_name)
        patch.status["phase"] = "Error"
        patch.status["message"] = str(e)
        raise kopf.TemporaryError(str(e), delay=60) from e
    patch.status["phase"] = "Synced"
    patch.status["exitId"] = exit_id
    patch.status["lastSyncedAt"] = datetime.now(timezone.utc).isoformat()
    patch.status["message"] = "Synced"
    logger.info("Synced PlatformEgressExit %s/%s -> exit=%s", namespace, cr_name, exit_id)


# No delete handler, for the connection path's reasons: instances bind the exit,
# and a resource vanishing from git is not a decision to cut them off.
