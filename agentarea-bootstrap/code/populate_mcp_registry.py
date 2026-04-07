"""Populate MCP servers from an external JSON registry into the system workspace.

Reads a JSON file (local path or URL) containing servers exported from the
public MCP registry (https://registry.modelcontextprotocol.io).

Env vars:
    MCP_REGISTRY_JSON  – Path or URL to the registry JSON file.
                         Empty string disables import.
    DATABASE_URL       – PostgreSQL connection string.
"""

import json
import os
import urllib.request
import uuid
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg2://user:password@localhost:5432/agentarea"
)
MCP_REGISTRY_JSON = os.environ.get("MCP_REGISTRY_JSON", "")

engine = create_engine(DATABASE_URL)


def load_registry(source: str) -> dict[str, Any]:
    """Load registry JSON from a local path or URL."""
    if source.startswith("http://") or source.startswith("https://"):
        req = urllib.request.Request(source, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    else:
        with open(source) as f:
            return json.load(f)


def _parse_raw_entry(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw registry entry (with 'server' key) into the flat format."""
    srv = raw.get("server", raw)

    name = srv.get("name", "")
    remotes = srv.get("remotes", [])
    packages = srv.get("packages", [])

    # Determine connection types and build entries
    entries = []

    # URL-type from remotes
    for remote in remotes:
        url = remote.get("url", "")
        headers = remote.get("headers", [])
        env_schema = [h for h in headers if isinstance(h, dict)]
        requires_auth = any(
            h.get("name", "").lower() in ("authorization", "api-key", "x-api-key")
            for h in env_schema
        )
        entries.append({
            "registry_id": name,
            "description": srv.get("description", ""),
            "version": srv.get("version", "latest"),
            "connection_type": "url",
            "transport": remote.get("type", ""),
            "remote_url": url,
            "requires_auth": requires_auth,
            "env_schema": env_schema,
            "json_spec": {},
            "raw_server_json": srv,
        })

    # Docker/command from packages
    for pkg in packages:
        registry_type = pkg.get("registryType", "")
        env_vars = pkg.get("environmentVariables", [])

        if registry_type == "docker":
            entries.append({
                "registry_id": name,
                "description": srv.get("description", ""),
                "version": srv.get("version", "latest"),
                "connection_type": "docker",
                "json_spec": {
                    "image": pkg.get("name", ""),
                    "args": pkg.get("arguments", []),
                },
                "env_schema": [e for e in env_vars if isinstance(e, dict)],
                "raw_server_json": srv,
            })
        elif registry_type in ("npm", "pypi"):
            runtime = pkg.get("runtime", "node" if registry_type == "npm" else "python")
            command = "npx" if runtime == "node" else "uvx"
            entries.append({
                "registry_id": name,
                "description": srv.get("description", ""),
                "version": srv.get("version", "latest"),
                "connection_type": "command",
                "package_registry": registry_type,
                "json_spec": {
                    "command": command,
                    "args": [pkg.get("name", ""), *(pkg.get("arguments", []))],
                },
                "env_schema": [e for e in env_vars if isinstance(e, dict)],
                "raw_server_json": srv,
            })

    # Fallback: if no remotes/packages, create a url entry with just the name
    if not entries:
        entries.append({
            "registry_id": name,
            "description": srv.get("description", ""),
            "version": srv.get("version", "latest"),
            "connection_type": "url",
            "json_spec": {},
            "env_schema": [],
            "raw_server_json": srv,
        })

    return entries


def upsert_registry_server(conn: Connection, entry: dict[str, Any]) -> bool:
    """Upsert a single registry server into the system workspace.

    Returns True if a new row was inserted.
    """
    registry_id = entry.get("registry_id", entry.get("name", ""))
    conn_type = entry.get("connection_type", "url")

    # Check if already exists by name + connection type tag
    result = conn.execute(
        text(
            "SELECT id FROM mcp_servers "
            "WHERE workspace_id = 'system' AND name = :name "
            "AND tags::text LIKE :tag_pattern"
        ),
        {"name": registry_id, "tag_pattern": f'%"{conn_type}"%'},
    ).fetchone()

    if result:
        # Update json_spec + remote_url for existing entries
        raw_json = entry.get("raw_server_json")
        remote_url = entry.get("remote_url", "")
        if raw_json:
            conn.execute(
                text(
                    "UPDATE mcp_servers SET json_spec = :json_spec, "
                    "remote_url = COALESCE(NULLIF(:remote_url, ''), remote_url), "
                    "registry_url = :registry_url, "
                    "updated_at = now() "
                    "WHERE id = :id"
                ),
                {
                    "id": result[0],
                    "json_spec": json.dumps(raw_json),
                    "remote_url": remote_url,
                    "registry_url": "https://registry.modelcontextprotocol.io",
                },
            )
        return False

    json_spec_field = entry.get("json_spec", {})
    raw_server_json = entry.get("raw_server_json")

    # Map connection type to MCPServer fields
    docker_image_url = ""
    cmd = None

    if conn_type == "docker":
        docker_image_url = json_spec_field.get("image", "")
    elif conn_type == "command":
        docker_image_url = "agentarea/mcp-bridge:latest"
        command = json_spec_field.get("command", "")
        args = json_spec_field.get("args", [])
        cmd = [command, *args] if command else None
    # url type: no image needed

    tags = ["registry", conn_type]
    if entry.get("package_registry"):
        tags.append(entry["package_registry"])
    if entry.get("requires_auth"):
        tags.append("requires-auth")
    transport = entry.get("transport") or json_spec_field.get("transport", "")
    if transport:
        tags.append(transport)

    server_id = str(uuid.uuid4())
    description = (entry.get("description") or "")[:500]
    version = entry.get("version") or "latest"
    env_schema = entry.get("env_schema", [])
    remote_url = entry.get("remote_url", "")

    conn.execute(
        text(
            """INSERT INTO mcp_servers
            (id, name, description, docker_image_url, version, tags,
             status, is_public, env_schema, cmd, created_by, workspace_id,
             json_spec, remote_url, registry_url,
             created_at, updated_at)
            VALUES
            (:id, :name, :description, :docker_image_url, :version,
             :tags, :status, :is_public, :env_schema, :cmd, :created_by,
             :workspace_id, :json_spec, :remote_url, :registry_url,
             now(), now())"""
        ),
        {
            "id": server_id,
            "name": registry_id,
            "description": description,
            "docker_image_url": docker_image_url,
            "version": version,
            "tags": json.dumps(tags),
            "status": "active",
            "is_public": True,
            "env_schema": json.dumps(env_schema),
            "cmd": json.dumps(cmd) if cmd else None,
            "created_by": "system",
            "workspace_id": "system",
            "json_spec": json.dumps(raw_server_json) if raw_server_json else None,
            "remote_url": remote_url,
            "registry_url": "https://registry.modelcontextprotocol.io",
        },
    )
    return True


def main() -> None:
    """Import MCP servers from the external registry JSON."""
    if not MCP_REGISTRY_JSON:
        print("⚠️  MCP_REGISTRY_JSON not set — skipping registry import")
        return

    print(f"Loading MCP registry from: {MCP_REGISTRY_JSON}")

    try:
        data = load_registry(MCP_REGISTRY_JSON)
    except Exception as e:
        print(f"❌ Failed to load registry: {e}")
        return

    raw_servers = data.get("servers", [])
    if not raw_servers:
        print("⚠️  Registry contains no servers")
        return

    print(f"Found {len(raw_servers)} servers in registry")

    # Parse raw entries into flat format
    entries = []
    for raw in raw_servers:
        if isinstance(raw, dict) and "server" in raw:
            entries.extend(_parse_raw_entry(raw))
        else:
            entries.append(raw)

    print(f"Expanded to {len(entries)} entries (including multiple connection types)")

    inserted = 0
    updated = 0
    try:
        with engine.begin() as conn:
            for entry in entries:
                try:
                    if upsert_registry_server(conn, entry):
                        inserted += 1
                    else:
                        updated += 1
                except Exception as e:
                    rid = entry.get("registry_id", "?")
                    print(f"  ⚠️  Skipping {rid}: {e}")

        print(f"✅ Registry import complete: {inserted} new, {updated} updated ({len(entries)} total)")

    except Exception as e:
        print(f"❌ Error importing registry: {e}")
        raise


if __name__ == "__main__":
    main()
