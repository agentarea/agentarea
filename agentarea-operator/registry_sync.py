"""RegistrySync reconciliation for the agentarea-operator.

Parses catalog source data (mcp_servers, skills, llm_providers, llm_models,
agents) and upserts the corresponding registry_items + target entities
into the database via raw SQL.

Parser shapes match agentarea_mcp.application.registry_service so registries
written against the Python platform are fed the same way here.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any

import yaml

logger = logging.getLogger("agentarea-operator.registry_sync")

# Keep in sync with agentarea_common.constants
PLATFORM_WORKSPACE_ID = "platform"
PLATFORM_PRINCIPAL_ID = "platform"

VALID_TYPES = (
    "mcp_servers",
    "skills",
    "llm_providers",
    "llm_models",
    "agents",
)


# ── Source fetching ──


def fetch_source(source_type: str, location: str, configmap_body: str | None = None) -> Any:
    """Return parsed JSON/YAML from a source.

    source_type:
      - "url":       location is http(s) URL
      - "file":      location is a filesystem path
      - "configMap": configmap_body already holds the raw text
    """
    if source_type == "configMap":
        if configmap_body is None:
            raise ValueError("configMap source requires configmap_body")
        raw = configmap_body
    elif source_type == "url":
        req = urllib.request.Request(  # noqa: S310
            location,
            headers={
                "Accept": "application/json, application/yaml, text/yaml, */*",
                "User-Agent": "agentarea-operator-registry-sync",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
    elif source_type == "file":
        with open(location) as f:
            raw = f.read()
    else:
        raise ValueError(f"Unknown source type: {source_type}")

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return yaml.safe_load(raw)


# ── Parsers ──


def _parse_mcp_servers(data: dict[str, Any]) -> list[dict[str, Any]]:
    servers = data.get("servers", [])
    if not servers:
        return []
    first = servers[0]
    if "server" in first:
        return _parse_standard_mcp(servers)
    return _parse_legacy_mcp(servers)


def _parse_legacy_mcp(servers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in servers:
        external_id = entry.get("registry_id") or entry.get("name")
        if not external_id:
            continue
        conn_type = entry.get("connection_type", "url")
        json_spec = entry.get("json_spec", {})
        ext_id = f"{external_id}/{conn_type}" if conn_type != "url" else external_id
        items.append(
            {
                "external_id": ext_id,
                "name": external_id,
                "description": (entry.get("description") or "")[:500],
                "version": entry.get("version") or "latest",
                "spec": {**json_spec, "connection_type": conn_type},
                "tags": [],
            }
        )
    return items


def _parse_standard_mcp(servers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in servers:
        server = entry.get("server", {})
        meta = entry.get("_meta", {}).get("io.modelcontextprotocol.registry/official", {})
        if not meta.get("isLatest", True):
            continue

        identifier = server.get("name") or ""
        if not identifier:
            continue
        title = server.get("title") or _humanize_identifier(identifier)
        description = (server.get("description") or "")[:500]
        version = server.get("version", "latest")
        for remote in server.get("remotes", []):
            url = remote.get("url")
            if not url:
                continue
            transport = remote.get("type", "streamable-http")
            raw_headers = remote.get("headers", [])
            env_schema = (
                [h for h in raw_headers if isinstance(h, dict)]
                if isinstance(raw_headers, list)
                else []
            )
            requires_auth = any(
                h.get("name", "").lower() in ("authorization", "api_key", "x-api-key", "token")
                for h in env_schema
            )
            tags = [transport]
            if requires_auth:
                tags.append("requires-auth")
            items.append(
                {
                    "external_id": identifier,
                    "name": title,
                    "description": description,
                    "version": version,
                    "spec": {
                        "connection_type": "url",
                        "url": url,
                        "transport": transport,
                        "env_schema": env_schema,
                        "raw_spec": server,
                    },
                    "tags": tags,
                }
            )

        for pkg in server.get("packages", []):
            if pkg.get("registryType") != "oci":
                continue
            image = pkg.get("name", "") or pkg.get("identifier", "")
            pkg_version = pkg.get("version", version)
            if not image:
                continue
            env_schema = [
                ev for ev in pkg.get("environmentVariables", []) if isinstance(ev, dict)
            ]
            items.append(
                {
                    "external_id": f"{identifier}/docker",
                    "name": title,
                    "description": description,
                    "version": pkg_version,
                    "spec": {
                        "connection_type": "docker",
                        "image": f"{image}:{pkg_version}" if ":" not in image else image,
                        "transport": "stdio",
                        "env_schema": env_schema,
                        "raw_spec": server,
                    },
                    "tags": ["docker", "oci"],
                }
            )

        for pkg in server.get("packages", []):
            reg_type = pkg.get("registryType", "")
            if reg_type not in ("npm", "pypi", "nuget", "mcpb"):
                continue
            pkg_name = pkg.get("name", "") or pkg.get("identifier", "")
            pkg_version = pkg.get("version", version)
            if not pkg_name:
                continue
            runtime_args = pkg.get("runtimeArgs", [])
            if runtime_args:
                command = runtime_args[0]
                args = runtime_args[1:]
            elif reg_type == "npm":
                command = "npx"
                args = ["-y", pkg_name]
            elif reg_type == "nuget":
                command = "dotnet"
                args = ["tool", "run", pkg_name]
            elif reg_type == "mcpb":
                command = "npx"
                args = ["-y", pkg_name]
            else:
                command = "uvx"
                args = [pkg_name]
            env_schema = [
                ev for ev in pkg.get("environmentVariables", []) if isinstance(ev, dict)
            ]
            items.append(
                {
                    "external_id": f"{identifier}/command",
                    "name": title,
                    "description": description,
                    "version": pkg_version,
                    "spec": {
                        "connection_type": "command",
                        "command": command,
                        "args": args,
                        "transport": "stdio",
                        "package_registry": reg_type,
                        "package_name": pkg_name,
                        "env_schema": env_schema,
                        "raw_spec": server,
                    },
                    "tags": ["command", reg_type],
                }
            )
    return items


def _parse_skills(data: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in data.get("skills", []):
        name = entry.get("name")
        if not name:
            continue
        items.append(
            {
                "external_id": name,
                "name": name,
                "description": entry.get("description"),
                "version": entry.get("version") or "1.0.0",
                "spec": {
                    "source_type": entry.get("source_type", "content"),
                    "content": entry.get("content"),
                    "source_url": entry.get("source_url"),
                },
                "tags": entry.get("tags", []),
            }
        )
    return items


def _parse_llm_providers(data: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in data.get("providers", []):
        provider_key = entry.get("provider_key")
        if not provider_key:
            continue
        items.append(
            {
                "external_id": provider_key,
                "name": entry.get("name") or provider_key,
                "description": entry.get("description"),
                "version": entry.get("version") or "1.0.0",
                "spec": {
                    "provider_key": provider_key,
                    "provider_type": entry.get("provider_type", provider_key),
                    "icon": entry.get("icon"),
                    "is_builtin": entry.get("is_builtin", True),
                },
                "tags": entry.get("tags", []),
            }
        )
    return items


def _parse_llm_models(data: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in data.get("models", []):
        provider_key = entry.get("provider_key")
        model_name = entry.get("model_name")
        if not provider_key or not model_name:
            continue
        items.append(
            {
                "external_id": f"{provider_key}/{model_name}",
                "name": entry.get("display_name") or model_name,
                "description": entry.get("description"),
                "version": entry.get("version") or "1.0.0",
                "spec": {
                    "provider_key": provider_key,
                    "model_name": model_name,
                    "context_window": entry.get("context_window", 4096),
                    "max_output_tokens": entry.get("max_output_tokens"),
                    "input_cost_per_token": entry.get("input_cost_per_token"),
                    "output_cost_per_token": entry.get("output_cost_per_token"),
                    "supports_function_calling": entry.get(
                        "supports_function_calling", False
                    ),
                    "is_active": entry.get("is_active", True),
                },
                "tags": entry.get("tags", []),
            }
        )
    return items


def _parse_agents(data: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in data.get("agents", []):
        name = entry.get("name")
        if not name:
            continue
        agent_id = entry.get("id")
        tools = entry.get("tools") or []
        if not isinstance(tools, list):
            tools = []
        items.append(
            {
                "external_id": str(agent_id) if agent_id else name,
                "name": name,
                "description": entry.get("description"),
                "version": entry.get("version") or "1.0.0",
                "spec": {
                    "id": agent_id,
                    "name": name,
                    "description": entry.get("description"),
                    "instruction": entry.get("instruction", ""),
                    "model_id": entry.get("model_id"),
                    "tools": tools,
                    "planning": entry.get("planning", False),
                    "events_config": entry.get("events_config"),
                },
                "tags": entry.get("tags", []),
            }
        )
    return items


def parse_source(registry_type: str, data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        data = {}
    if registry_type == "mcp_servers":
        return _parse_mcp_servers(data)
    if registry_type == "skills":
        return _parse_skills(data)
    if registry_type == "llm_providers":
        return _parse_llm_providers(data)
    if registry_type == "llm_models":
        return _parse_llm_models(data)
    if registry_type == "agents":
        return _parse_agents(data)
    raise ValueError(f"Unknown registry type: {registry_type}")


# ── Reconcile ──


def reconcile(
    conn,
    cr_name: str,
    registry_type: str,
    source_type: str,
    source_location: str,
    configmap_body: str | None,
    workspace_id: str,
) -> dict[str, int]:
    """Fetch catalog source and upsert registry + items + target entities.

    conn is an active SQLAlchemy Connection (sync). Caller owns transaction.
    Returns stats dict: {total, new, updated}.
    """
    if registry_type not in VALID_TYPES:
        raise ValueError(f"Unknown registry type: {registry_type}")

    data = fetch_source(source_type, source_location, configmap_body)
    parsed = parse_source(registry_type, data)
    logger.info("Parsed %d items for %s (%s)", len(parsed), cr_name, registry_type)

    registry_id = _upsert_registry(
        conn,
        name=cr_name,
        registry_type=registry_type,
        source_type=source_type,
        source_url=source_location,
        workspace_id=workspace_id,
    )

    new_count = 0
    updated_count = 0

    for item in parsed:
        item["registry_url"] = source_location
        existing = _get_registry_item(conn, registry_id, item["external_id"])
        if existing:
            _update_registry_item(conn, existing["id"], item)
            entity_id = existing["installed_entity_id"]
            if entity_id:
                _update_entity(
                    conn, registry_type, entity_id, item, workspace_id, existing["id"]
                )
            updated_count += 1
        else:
            item_id = _create_registry_item(conn, registry_id, item, workspace_id)
            entity_id = _create_entity(conn, registry_type, item, workspace_id, item_id)
            if entity_id:
                conn.execute(
                    _text(
                        "UPDATE registry_items SET installed_entity_id = :eid, "
                        "installed_version = :v WHERE id = :id"
                    ),
                    {"eid": entity_id, "v": item.get("version") or "latest", "id": item_id},
                )
            new_count += 1

    conn.execute(
        _text(
            "UPDATE registries SET last_synced_at = :ts, last_sync_error = NULL, "
            "item_count = :n, updated_at = now() WHERE id = :id"
        ),
        {"ts": datetime.now(timezone.utc), "n": len(parsed), "id": registry_id},
    )

    return {"total": len(parsed), "new": new_count, "updated": updated_count}


# ── DB helpers (raw SQL, sync) ──


def _text(sql: str):
    # Lazy import to avoid circular + keep this module importable without a DB
    from sqlalchemy import text

    return text(sql)


def _upsert_registry(
    conn,
    *,
    name: str,
    registry_type: str,
    source_type: str,
    source_url: str,
    workspace_id: str,
) -> str:
    # registries are global catalog infrastructure (no workspace_id column).
    row = conn.execute(
        _text("SELECT id FROM registries WHERE name = :name"),
        {"name": name},
    ).fetchone()
    if row:
        registry_id = str(row[0])
        conn.execute(
            _text(
                "UPDATE registries SET registry_type = :rt, source_type = :st, "
                "source_url = :url, is_active = true, updated_at = now() WHERE id = :id"
            ),
            {
                "id": registry_id,
                "rt": registry_type,
                "st": source_type,
                "url": source_url,
            },
        )
        return registry_id
    registry_id = str(uuid.uuid4())
    conn.execute(
        _text(
            "INSERT INTO registries (id, name, registry_type, source_type, source_url, "
            "is_active, sync_mode, created_at, updated_at) "
            "VALUES (:id, :name, :rt, :st, :url, true, 'manual', now(), now())"
        ),
        {
            "id": registry_id,
            "name": name,
            "rt": registry_type,
            "st": source_type,
            "url": source_url,
        },
    )
    return registry_id


def _get_registry_item(conn, registry_id: str, external_id: str) -> dict | None:
    row = conn.execute(
        _text(
            "SELECT id, installed_entity_id, installed_version FROM registry_items "
            "WHERE registry_id = :rid AND external_id = :ext"
        ),
        {"rid": registry_id, "ext": external_id},
    ).fetchone()
    if not row:
        return None
    return {
        "id": str(row[0]),
        "installed_entity_id": str(row[1]) if row[1] else None,
        "installed_version": row[2],
    }


def _create_registry_item(
    conn, registry_id: str, item: dict[str, Any], workspace_id: str
) -> str:
    item_id = str(uuid.uuid4())
    conn.execute(
        _text(
            "INSERT INTO registry_items (id, registry_id, external_id, name, description, "
            "version, spec, tags, update_available, created_at, updated_at) "
            "VALUES (:id, :rid, :ext, :name, :desc, :ver, "
            "CAST(:spec AS JSONB), CAST(:tags AS JSONB), false, now(), now())"
        ),
        {
            "id": item_id,
            "rid": registry_id,
            "ext": item["external_id"],
            "name": item["name"],
            "desc": item.get("description"),
            "ver": item.get("version"),
            "spec": json.dumps(item.get("spec") or {}),
            "tags": json.dumps(item.get("tags") or []),
        },
    )
    return item_id


def _update_registry_item(conn, item_id: str, item: dict[str, Any]) -> None:
    conn.execute(
        _text(
            "UPDATE registry_items SET name = :name, description = :desc, version = :ver, "
            "spec = CAST(:spec AS JSONB), tags = CAST(:tags AS JSONB), updated_at = now() "
            "WHERE id = :id"
        ),
        {
            "id": item_id,
            "name": item["name"],
            "desc": item.get("description"),
            "ver": item.get("version"),
            "spec": json.dumps(item.get("spec") or {}),
            "tags": json.dumps(item.get("tags") or []),
        },
    )


# ── Entity dispatchers ──


def _create_entity(
    conn,
    registry_type: str,
    item: dict[str, Any],
    workspace_id: str,
    registry_item_id: str | None = None,
) -> str | None:
    if registry_type == "llm_providers":
        return _upsert_provider_spec(conn, item, workspace_id)
    if registry_type == "llm_models":
        return _upsert_model_spec(conn, item, workspace_id)
    if registry_type == "agents":
        # Agents live in the catalog only (ADR-003): the registry_item itself is
        # the built-in definition. No tenant `agents` row is materialized on sync;
        # a real row is created copy-on-write when a user edits the catalog agent.
        return None
    if registry_type == "mcp_servers":
        return _upsert_mcp_server(conn, item, workspace_id, registry_item_id)
    if registry_type == "skills":
        return _upsert_skill(conn, item, workspace_id, registry_item_id)
    return None


def _update_entity(
    conn,
    registry_type: str,
    entity_id: str,
    item: dict[str, Any],
    workspace_id: str,
    registry_item_id: str | None = None,
) -> None:
    # Re-upsert handles updates uniformly for our catalog shapes.
    _create_entity(conn, registry_type, item, workspace_id, registry_item_id)


def _upsert_provider_spec(
    conn, item: dict[str, Any], workspace_id: str
) -> str:
    spec = item.get("spec") or {}
    provider_key = spec["provider_key"]
    row = conn.execute(
        _text("SELECT id FROM provider_specs WHERE provider_key = :pk"),
        {"pk": provider_key},
    ).fetchone()
    if row:
        pid = str(row[0])
        conn.execute(
            _text(
                "UPDATE provider_specs SET name = :name, description = :desc, "
                "provider_type = :pt, icon = :icon, is_builtin = :bi, updated_at = now() "
                "WHERE id = :id"
            ),
            {
                "id": pid,
                "name": item["name"],
                "desc": item.get("description"),
                "pt": spec.get("provider_type", provider_key),
                "icon": spec.get("icon"),
                "bi": spec.get("is_builtin", True),
            },
        )
        return pid
    pid = str(uuid.uuid4())
    conn.execute(
        _text(
            "INSERT INTO provider_specs (id, provider_key, name, description, provider_type, "
            "icon, is_builtin, workspace_id, created_by, created_at, updated_at) "
            "VALUES (:id, :pk, :name, :desc, :pt, :icon, :bi, :ws, :created_by, now(), now())"
        ),
        {
            "id": pid,
            "pk": provider_key,
            "name": item["name"],
            "desc": item.get("description"),
            "pt": spec.get("provider_type", provider_key),
            "icon": spec.get("icon"),
            "bi": spec.get("is_builtin", True),
            "ws": workspace_id,
            "created_by": PLATFORM_PRINCIPAL_ID,
        },
    )
    return pid


def _upsert_model_spec(conn, item: dict[str, Any], workspace_id: str) -> str:
    spec = item.get("spec") or {}
    provider_key = spec["provider_key"]
    model_name = spec["model_name"]

    prow = conn.execute(
        _text("SELECT id FROM provider_specs WHERE provider_key = :pk"),
        {"pk": provider_key},
    ).fetchone()
    if not prow:
        raise ValueError(
            f"provider_spec '{provider_key}' not found; sync llm_providers registry first"
        )
    provider_spec_id = str(prow[0])

    mrow = conn.execute(
        _text(
            "SELECT id FROM model_specs WHERE provider_spec_id = :pid AND model_name = :mn"
        ),
        {"pid": provider_spec_id, "mn": model_name},
    ).fetchone()
    if mrow:
        mid = str(mrow[0])
        conn.execute(
            _text(
                "UPDATE model_specs SET display_name = :dn, description = :desc, "
                "context_window = :cw, max_output_tokens = :mot, "
                "input_cost_per_token = :icpt, output_cost_per_token = :ocpt, "
                "supports_function_calling = :sfc, is_active = :active, updated_at = now() "
                "WHERE id = :id"
            ),
            {
                "id": mid,
                "dn": item["name"],
                "desc": item.get("description"),
                "cw": spec.get("context_window", 4096),
                "mot": spec.get("max_output_tokens"),
                "icpt": spec.get("input_cost_per_token"),
                "ocpt": spec.get("output_cost_per_token"),
                "sfc": spec.get("supports_function_calling", False),
                "active": spec.get("is_active", True),
            },
        )
        return mid
    mid = str(uuid.uuid4())
    conn.execute(
        _text(
            "INSERT INTO model_specs (id, provider_spec_id, model_name, display_name, "
            "description, context_window, max_output_tokens, input_cost_per_token, "
            "output_cost_per_token, supports_function_calling, is_active, source, "
            "workspace_id, created_by, created_at, updated_at) "
            "VALUES (:id, :pid, :mn, :dn, :desc, :cw, "
            ":mot, :icpt, :ocpt, :sfc, :active, 'official', :ws, :created_by, now(), now())"
        ),
        {
            "id": mid,
            "pid": provider_spec_id,
            "mn": model_name,
            "dn": item["name"],
            "desc": item.get("description"),
            "cw": spec.get("context_window", 4096),
            "mot": spec.get("max_output_tokens"),
            "icpt": spec.get("input_cost_per_token"),
            "ocpt": spec.get("output_cost_per_token"),
            "sfc": spec.get("supports_function_calling", False),
            "active": spec.get("is_active", True),
            "ws": workspace_id,
            "created_by": PLATFORM_PRINCIPAL_ID,
        },
    )
    return mid


def _upsert_mcp_server(
    conn, item: dict[str, Any], workspace_id: str, registry_item_id: str | None = None
) -> str:
    spec = item.get("spec") or {}
    conn_type = spec.get("connection_type", "url")
    docker_image_url = ""
    cmd_list: list[str] | None = None
    if conn_type == "docker":
        docker_image_url = spec.get("image", "")
    elif conn_type == "command":
        docker_image_url = "agentarea/mcp-bridge:latest"
        command_str = spec.get("command", "")
        args = spec.get("args", []) or []
        if command_str:
            cmd_list = [command_str, *args]
    remote_url = spec.get("url") if conn_type == "url" else None
    raw_spec = spec.get("raw_spec") or spec
    tags = ["registry", conn_type]
    for tag in item.get("tags") or []:
        if tag and tag not in tags:
            tags.append(tag)

    row = conn.execute(
        _text(
            "SELECT id FROM mcp_servers WHERE name = :name AND workspace_id = :ws"
        ),
        {"name": item["name"], "ws": workspace_id},
    ).fetchone()
    tags_json = json.dumps(tags)
    env_schema_json = json.dumps(spec.get("env_schema") or [])
    json_spec_json = json.dumps(raw_spec) if raw_spec else None
    if row:
        sid = str(row[0])
        conn.execute(
            _text(
                "UPDATE mcp_servers SET description = :desc, docker_image_url = :img, "
                "version = :ver, tags = CAST(:tags AS JSONB), remote_url = :rurl, "
                "env_schema = CAST(:env AS JSONB), cmd = CAST(:cmd AS JSONB), "
                "registry_item_id = :rid, json_spec = CAST(:json_spec AS JSONB), "
                "registry_url = :registry_url, updated_at = now() WHERE id = :id"
            ),
            {
                "id": sid,
                "desc": item.get("description") or "",
                "img": docker_image_url,
                "ver": item.get("version") or "latest",
                "tags": tags_json,
                "env": env_schema_json,
                "rurl": remote_url,
                "cmd": json.dumps(cmd_list) if cmd_list else None,
                "rid": registry_item_id,
                "json_spec": json_spec_json,
                "registry_url": item.get("registry_url"),
            },
        )
        return sid
    sid = str(uuid.uuid4())
    slug = _unique_mcp_slug(conn, workspace_id, item["name"])
    conn.execute(
        _text(
            "INSERT INTO mcp_servers (id, name, slug, description, docker_image_url, version, "
            "tags, is_public, env_schema, cmd, remote_url, registry_item_id, json_spec, "
            "registry_url, source, workspace_id, created_by, created_at, updated_at) "
            "VALUES (:id, :name, :slug, :desc, :img, :ver, CAST(:tags AS JSONB), false, "
            "CAST(:env AS JSONB), CAST(:cmd AS JSONB), :rurl, :rid, "
            "CAST(:json_spec AS JSONB), :registry_url, 'official', :ws, :created_by, now(), now())"
        ),
        {
            "id": sid,
            "name": item["name"],
            "slug": slug,
            "desc": item.get("description") or "",
            "img": docker_image_url,
            "ver": item.get("version") or "latest",
            "tags": tags_json,
            "env": env_schema_json,
            "cmd": json.dumps(cmd_list) if cmd_list else None,
            "rurl": remote_url,
            "rid": registry_item_id,
            "json_spec": json_spec_json,
            "registry_url": item.get("registry_url"),
            "ws": workspace_id,
            "created_by": PLATFORM_PRINCIPAL_ID,
        },
    )
    return sid


def _generate_slug(name: str) -> str:
    """ASCII, lowercase, hyphenated slug. Kept in sync with
    agentarea_common.utils.slug.generate_slug."""
    if not isinstance(name, str):
        name = str(name or "")
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    if len(slug) > 100:
        slug = slug[:100].rstrip("-")
    return slug or "item"


def _humanize_identifier(identifier: str) -> str:
    name = identifier.rsplit("/", 1)[-1] if "/" in identifier else identifier
    abbrevs = {"mcp", "api", "ai", "db", "sql", "ssh", "aws", "gcp", "cli", "sdk", "llm"}
    parts = name.replace("-", " ").replace("_", " ").split()
    return " ".join(p.upper() if p.lower() in abbrevs else p.capitalize() for p in parts)


def _unique_mcp_slug(conn, workspace_id: str, name: str) -> str:
    base = _generate_slug(name)

    def _taken(candidate: str) -> bool:
        return (
            conn.execute(
                _text(
                    "SELECT 1 FROM mcp_servers "
                    "WHERE workspace_id = :ws AND slug = :slug LIMIT 1"
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


def _unique_skill_slug(conn, workspace_id: str, name: str) -> str:
    """Workspace-unique slug via SELECT collision checks.

    Safe within the operator's single per-registry transaction (own writes are
    visible to later reads in the same tx); cross-pass idempotency is guaranteed
    separately by the registry_item_id conflict target.
    """
    base = _generate_slug(name)

    def _taken(candidate: str) -> bool:
        return (
            conn.execute(
                _text("SELECT 1 FROM skills WHERE workspace_id = :ws AND slug = :slug LIMIT 1"),
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


def _upsert_skill(
    conn, item: dict[str, Any], workspace_id: str, registry_item_id: str | None = None
) -> str:
    """Idempotently upsert a catalog skill keyed on its registry item.

    Dedup is by ``registry_item_id`` (provenance), backed by the partial unique
    index ``uq_skills_registry_item`` — race-proof under overlapping reconciles,
    unlike the previous SELECT-then-INSERT by name. The slug is immutable and
    derived once at creation.
    """
    spec = item.get("spec") or {}

    # Dedup by provenance: one skill per registry item. Re-sync updates in place
    # and never touches the (immutable) slug.
    existing = (
        conn.execute(
            _text("SELECT id FROM skills WHERE registry_item_id = :rid"),
            {"rid": registry_item_id},
        ).fetchone()
        if registry_item_id
        else None
    )
    if existing:
        sid = str(existing[0])
        conn.execute(
            _text(
                "UPDATE skills SET description = :desc, content = :content, "
                "source_url = :url, updated_at = now() WHERE id = :id"
            ),
            {
                "id": sid,
                "desc": item.get("description"),
                "content": spec.get("content"),
                "url": spec.get("source_url"),
            },
        )
        return sid

    slug = _unique_skill_slug(conn, workspace_id, item["name"])
    row = conn.execute(
        _text(
            "INSERT INTO skills (id, name, slug, description, source_type, content, "
            "source_url, registry_item_id, source, workspace_id, created_by, "
            "created_at, updated_at) "
            "VALUES (:id, :name, :slug, :desc, :st, :content, :url, :rid, 'official', :ws, "
            ":created_by, now(), now()) "
            "ON CONFLICT (registry_item_id) WHERE registry_item_id IS NOT NULL "
            "DO UPDATE SET description = EXCLUDED.description, content = EXCLUDED.content, "
            "source_url = EXCLUDED.source_url, updated_at = now() "
            "RETURNING id"
        ),
        {
            "id": str(uuid.uuid4()),
            "name": item["name"],
            "slug": slug,
            "desc": item.get("description"),
            "st": spec.get("source_type", "content"),
            "content": spec.get("content"),
            "url": spec.get("source_url"),
            "rid": registry_item_id,
            "ws": workspace_id,
            "created_by": PLATFORM_PRINCIPAL_ID,
        },
    ).fetchone()
    return str(row[0])
