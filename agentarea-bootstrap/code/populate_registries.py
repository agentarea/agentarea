"""Populate registries from Helm values (IaaC).

Reads REGISTRIES_CONFIG env var — a JSON array of registry definitions:
  [
    {
      "name": "MCP Public Registry",
      "type": "mcp_servers",
      "source_type": "url",
      "source_url": "https://s3.amazonaws.com/.../mcp-servers.json",
      "sync_mode": "manual"
    },
    {
      "name": "Skills Registry",
      "type": "skills",
      "source_type": "url",
      "source_url": "https://s3.amazonaws.com/.../skills.yaml",
      "sync_mode": "manual"
    }
  ]

For each registry:
  1. Upsert into `registries` table (workspace_id=system)
  2. Fetch the source URL (auto-detect JSON or YAML)
  3. Upsert `registry_items` for each entry
  4. Auto-create entity specs (mcp_servers or skills) for new items

Env vars:
    REGISTRIES_CONFIG  – JSON array of registry configs. Empty = skip.
    DATABASE_URL     – PostgreSQL connection string.
"""

import json
import os
import urllib.request
import uuid
from typing import Any

import yaml
from code.db import engine
from sqlalchemy import text
from sqlalchemy.engine import Connection

REGISTRIES_CONFIG = os.environ.get("REGISTRIES_CONFIG", os.environ.get("REGISTRIES_JSON", ""))


def fetch_source(source_url: str) -> dict[str, Any]:
    """Fetch data from URL or local path, auto-detect JSON vs YAML."""
    if source_url.startswith("http://") or source_url.startswith("https://"):
        req = urllib.request.Request(
            source_url,
            headers={
                "Accept": "application/json, application/yaml, text/yaml, */*",
                "User-Agent": "agentarea-registry-sync",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            content_type = resp.headers.get("Content-Type", "")
    else:
        with open(source_url) as f:
            raw = f.read()
        content_type = ""

    if "yaml" in content_type or source_url.endswith((".yaml", ".yml")):
        return yaml.safe_load(raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return yaml.safe_load(raw)


def upsert_registry(conn: Connection, config: dict[str, Any]) -> str:
    """Upsert a registry row. Returns the registry ID."""
    name = config["name"]
    registry_type = config.get("type", "mcp_servers")
    source_type = config.get("source_type", "url")
    source_url = config["source_url"]
    sync_mode = config.get("sync_mode", "manual")
    description = config.get("description", "")

    # Check if exists by name in system workspace
    row = conn.execute(
        text("SELECT id FROM registries WHERE workspace_id = 'system' AND name = :name"),
        {"name": name},
    ).fetchone()

    if row:
        registry_id = str(row[0])
        conn.execute(
            text(
                "UPDATE registries SET source_url = :source_url, source_type = :source_type, "
                "registry_type = :registry_type, sync_mode = :sync_mode, "
                "description = :description, updated_at = now() "
                "WHERE id = :id"
            ),
            {
                "id": registry_id,
                "source_url": source_url,
                "source_type": source_type,
                "registry_type": registry_type,
                "sync_mode": sync_mode,
                "description": description,
            },
        )
        return registry_id

    registry_id = str(uuid.uuid4())
    conn.execute(
        text(
            "INSERT INTO registries "
            "(id, name, description, registry_type, source_type, source_url, sync_mode, "
            " is_active, item_count, workspace_id, created_by, created_at, updated_at) "
            "VALUES (:id, :name, :description, :registry_type, :source_type, :source_url, "
            " :sync_mode, true, 0, 'system', 'system', now(), now())"
        ),
        {
            "id": registry_id,
            "name": name,
            "description": description,
            "registry_type": registry_type,
            "source_type": source_type,
            "source_url": source_url,
            "sync_mode": sync_mode,
        },
    )
    return registry_id


# ── Parsers (match registry_service.py logic) ──


def parse_mcp_servers(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse MCP servers — auto-detects standard vs legacy format."""
    servers = data.get("servers", [])
    if not servers:
        return []
    # Standard format has nested "server" key
    if "server" in servers[0]:
        return _parse_standard_mcp_registry(servers)
    return _parse_legacy_mcp_servers(servers)


def _parse_standard_mcp_registry(servers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse official MCP registry format (remotes + packages)."""
    items = []
    for entry in servers:
        server = entry.get("server", {})
        meta = entry.get("_meta", {}).get("io.modelcontextprotocol.registry/official", {})
        if not meta.get("isLatest", True):
            continue
        identifier = server.get("name", "")
        if not identifier:
            continue
        title = server.get("title", identifier)
        description = (server.get("description") or "")[:500]
        version = server.get("version", "latest")

        # Remote endpoints → connection_type: "url"
        for remote in server.get("remotes", []):
            transport = remote.get("type", "streamable-http")
            url = remote.get("url", "")
            if not url:
                continue
            # Headers are KeyValueInput arrays — keep raw for env_schema
            raw_headers = remote.get("headers", [])
            env_schema = [h for h in raw_headers if isinstance(h, dict)] if isinstance(raw_headers, list) else []
            requires_auth = any(
                h.get("name", "").lower() in ("authorization", "api-key", "x-api-key")
                for h in env_schema
            )
            tags = [transport]
            if requires_auth:
                tags.append("requires-auth")
            items.append({
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
            })

        # OCI packages → connection_type: "docker"
        for pkg in server.get("packages", []):
            if pkg.get("registryType") != "oci":
                continue
            image = pkg.get("name", "") or pkg.get("identifier", "")
            pkg_version = pkg.get("version", version)
            if not image:
                continue
            env_schema = [
                {"name": ev.get("name", ""), "description": ev.get("description", ""), "required": ev.get("isRequired", False)}
                for ev in pkg.get("environmentVariables", [])
            ]
            items.append({
                "external_id": f"{identifier}/docker",
                "name": title,
                "description": description,
                "version": pkg_version,
                "spec": {"connection_type": "docker", "image": f"{image}:{pkg_version}" if ":" not in image else image, "transport": "stdio", "env_schema": env_schema, "raw_spec": server},
                "tags": ["docker", "oci"],
            })

        # npm/pypi packages → connection_type: "command"
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
                {"name": ev.get("name", ""), "description": ev.get("description", ""), "required": ev.get("isRequired", False)}
                for ev in pkg.get("environmentVariables", [])
            ]
            items.append({
                "external_id": f"{identifier}/command",
                "name": title,
                "description": description,
                "version": pkg_version,
                "spec": {"connection_type": "command", "command": command, "args": args, "transport": "stdio", "package_registry": reg_type, "package_name": pkg_name, "env_schema": env_schema, "raw_spec": server},
                "tags": ["command", reg_type],
            })
    return items


def _parse_legacy_mcp_servers(servers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse legacy agentarea format (registry_id + connection_type + json_spec)."""
    items = []
    for entry in servers:
        external_id = entry.get("registry_id", entry.get("name", ""))
        if not external_id:
            continue
        conn_type = entry.get("connection_type", "url")
        json_spec = entry.get("json_spec", {})
        ext_id = f"{external_id}/{conn_type}" if conn_type != "url" else external_id
        tags = []
        if entry.get("package_registry"):
            tags.append(entry["package_registry"])
        if entry.get("requires_auth"):
            tags.append("requires-auth")
        transport = entry.get("transport") or json_spec.get("transport", "")
        if transport:
            tags.append(transport)
        spec = {**json_spec, "connection_type": conn_type}
        if entry.get("env_schema"):
            spec["env_schema"] = entry["env_schema"]
        items.append({
            "external_id": ext_id,
            "name": external_id,
            "description": (entry.get("description") or "")[:500],
            "version": entry.get("version") or "latest",
            "spec": spec,
            "tags": tags,
        })
    return items


def parse_skills(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse skills registry format into catalog items."""
    skills = data.get("skills", [])
    items = []
    for entry in skills:
        name = entry.get("name", "")
        if not name:
            continue
        items.append({
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
        })
    return items


# ── Entity creators ──


def create_mcp_server(conn: Connection, item_id: str, item: dict[str, Any]) -> str:
    """Create an mcp_servers row from a catalog item. Returns server ID."""
    spec = item.get("spec", {})
    conn_type = spec.get("connection_type", "url")
    version = item.get("version", "latest")
    description = item.get("description") or ""

    docker_image_url = ""
    cmd = None
    remote_url = ""
    if conn_type == "docker":
        docker_image_url = spec.get("image", "")
    elif conn_type == "command":
        docker_image_url = "agentarea/mcp-bridge:latest"
        command = spec.get("command", "")
        args = spec.get("args", [])
        cmd = [command, *args] if command else None
    elif conn_type == "url":
        remote_url = spec.get("url", "")

    server_tags = ["registry", conn_type]
    transport = spec.get("transport", "")
    if transport:
        server_tags.append(transport)

    env_schema = spec.get("env_schema", [])
    raw_spec = spec.get("raw_spec")

    server_id = str(uuid.uuid4())
    conn.execute(
        text(
            "INSERT INTO mcp_servers "
            "(id, name, description, docker_image_url, version, tags, "
            " status, is_public, env_schema, cmd, registry_item_id, "
            " remote_url, json_spec, registry_url, "
            " created_by, workspace_id, created_at, updated_at) "
            "VALUES "
            "(:id, :name, :desc, :docker_image_url, :version, :tags, "
            " :status, :is_public, :env_schema, :cmd, :registry_item_id, "
            " :remote_url, :json_spec, :registry_url, "
            " :created_by, :workspace_id, now(), now())"
        ),
        {
            "id": server_id,
            "name": item["name"],
            "desc": description,
            "docker_image_url": docker_image_url,
            "version": version,
            "tags": json.dumps(server_tags),
            "status": "active",
            "is_public": True,
            "env_schema": json.dumps(env_schema),
            "cmd": json.dumps(cmd) if cmd else None,
            "registry_item_id": item_id,
            "remote_url": remote_url,
            "json_spec": json.dumps(raw_spec) if raw_spec else None,
            "registry_url": "https://registry.modelcontextprotocol.io",
            "created_by": "system",
            "workspace_id": "system",
        },
    )
    return server_id


def create_skill(conn: Connection, item_id: str, item: dict[str, Any]) -> str:
    """Create a skills row from a catalog item. Returns skill ID."""
    spec = item.get("spec", {})
    skill_id = str(uuid.uuid4())
    conn.execute(
        text(
            "INSERT INTO skills "
            "(id, name, description, source_type, content, source_url, "
            " registry_item_id, created_by, workspace_id, created_at, updated_at) "
            "VALUES "
            "(:id, :name, :desc, :source_type, :content, :source_url, "
            " :registry_item_id, :created_by, :workspace_id, now(), now())"
        ),
        {
            "id": skill_id,
            "name": item["name"],
            "desc": item.get("description") or "",
            "source_type": spec.get("source_type", "content"),
            "content": spec.get("content"),
            "source_url": spec.get("source_url"),
            "registry_item_id": item_id,
            "created_by": "system",
            "workspace_id": "system",
        },
    )
    return skill_id


# ── Sync ──


def sync_registry(
    conn: Connection, registry_id: str, registry_type: str, source_url: str
) -> dict[str, int]:
    """Fetch source, upsert registry_items, auto-create entities for new items."""
    data = fetch_source(source_url)

    if registry_type == "mcp_servers":
        parsed_items = parse_mcp_servers(data)
    elif registry_type == "skills":
        parsed_items = parse_skills(data)
    else:
        print(f"    Unknown registry_type: {registry_type}")
        return {"new_specs": 0, "unchanged": 0, "total": 0}

    new_specs = 0
    unchanged = 0

    for item_data in parsed_items:
        ext_id = item_data["external_id"]

        # Check if registry_item exists
        existing = conn.execute(
            text(
                "SELECT id, installed_entity_id, installed_version FROM registry_items "
                "WHERE registry_id = :registry_id AND external_id = :external_id "
                "AND workspace_id = 'system'"
            ),
            {"registry_id": registry_id, "external_id": ext_id},
        ).fetchone()

        if existing:
            item_id = str(existing[0])
            installed_version = existing[2]
            version = item_data.get("version", "latest")
            update_available = installed_version is not None and installed_version != version
            conn.execute(
                text(
                    "UPDATE registry_items SET name = :name, description = :desc, "
                    "version = :version, spec = :spec, tags = :tags, "
                    "update_available = :update_available, updated_at = now() "
                    "WHERE id = :id"
                ),
                {
                    "id": item_id,
                    "name": item_data["name"],
                    "desc": (item_data.get("description") or "")[:500],
                    "version": version,
                    "spec": json.dumps(item_data.get("spec", {})),
                    "tags": json.dumps(item_data.get("tags", [])),
                    "update_available": update_available,
                },
            )
            unchanged += 1
        else:
            # New item: create registry_item + entity
            item_id = str(uuid.uuid4())
            version = item_data.get("version", "latest")

            # Create entity based on registry_type
            if registry_type == "mcp_servers":
                entity_id = create_mcp_server(conn, item_id, item_data)
            elif registry_type == "skills":
                entity_id = create_skill(conn, item_id, item_data)
            else:
                continue

            # Create registry_item
            conn.execute(
                text(
                    "INSERT INTO registry_items "
                    "(id, registry_id, external_id, name, description, version, "
                    " spec, tags, installed_entity_id, "
                    " update_available, installed_version, "
                    " workspace_id, created_by, created_at, updated_at) "
                    "VALUES "
                    "(:id, :registry_id, :external_id, :name, :desc, :version, "
                    " :spec, :tags, :installed_entity_id, "
                    " false, :installed_version, "
                    " 'system', 'system', now(), now())"
                ),
                {
                    "id": item_id,
                    "registry_id": registry_id,
                    "external_id": ext_id,
                    "name": item_data["name"],
                    "desc": (item_data.get("description") or "")[:500],
                    "version": version,
                    "spec": json.dumps(item_data.get("spec", {})),
                    "tags": json.dumps(item_data.get("tags", [])),
                    "installed_entity_id": entity_id,
                    "installed_version": version,
                },
            )
            new_specs += 1

    # Update registry metadata
    total = new_specs + unchanged
    conn.execute(
        text(
            "UPDATE registries SET last_synced_at = now(), last_sync_error = NULL, "
            "item_count = :count, updated_at = now() WHERE id = :id"
        ),
        {"id": registry_id, "count": total},
    )

    return {"new_specs": new_specs, "unchanged": unchanged, "total": total}


def main() -> None:
    """Create registries from Helm values and run initial sync."""
    if not REGISTRIES_CONFIG:
        print("  REGISTRIES_CONFIG not set — skipping registry setup")
        return

    try:
        registries = json.loads(REGISTRIES_CONFIG)
    except json.JSONDecodeError as e:
        print(f"  Failed to parse REGISTRIES_CONFIG: {e}")
        return

    if not registries:
        print("  No registries configured — skipping")
        return

    print(f"  Processing {len(registries)} configured registries")

    with engine.begin() as conn:
        for config in registries:
            name = config.get("name", "unnamed")
            source_url = config.get("source_url", "")
            registry_type = config.get("type", "mcp_servers")
            if not source_url:
                print(f"    Skipping {name}: no source_url")
                continue

            try:
                registry_id = upsert_registry(conn, config)
                print(f"    Registry '{name}' ({registry_type}) → {registry_id}")

                print(f"    Syncing from {source_url}...")
                stats = sync_registry(conn, registry_id, registry_type, source_url)
                print(
                    f"    Synced: {stats['new_specs']} new specs, "
                    f"{stats['unchanged']} unchanged, {stats['total']} total"
                )
            except Exception as e:
                print(f"    Failed to sync '{name}': {e}")
                try:
                    conn.execute(
                        text(
                            "UPDATE registries SET last_sync_error = :err, updated_at = now() "
                            "WHERE id = :id"
                        ),
                        {"id": registry_id, "err": str(e)},
                    )
                except Exception:
                    pass


if __name__ == "__main__":
    main()
