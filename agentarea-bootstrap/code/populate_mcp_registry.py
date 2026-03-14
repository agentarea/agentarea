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
        return False  # already imported

    json_spec = entry.get("json_spec", {})

    # Map connection type to MCPServer fields
    docker_image_url = ""
    cmd = None

    if conn_type == "docker":
        docker_image_url = json_spec.get("image", "")
    elif conn_type == "command":
        docker_image_url = "agentarea/mcp-bridge:latest"
        command = json_spec.get("command", "")
        args = json_spec.get("args", [])
        cmd = [command, *args] if command else None
    # url type: no image needed

    tags = ["registry", conn_type]
    if entry.get("package_registry"):
        tags.append(entry["package_registry"])
    if entry.get("requires_auth"):
        tags.append("requires-auth")
    transport = entry.get("transport") or json_spec.get("transport", "")
    if transport:
        tags.append(transport)

    server_id = str(uuid.uuid4())
    description = (entry.get("description") or "")[:500]
    version = entry.get("version") or "latest"
    env_schema = entry.get("env_schema", [])

    conn.execute(
        text(
            """INSERT INTO mcp_servers
            (id, name, description, docker_image_url, version, tags,
             status, is_public, env_schema, cmd, created_by, workspace_id,
             created_at, updated_at)
            VALUES
            (:id, :name, :description, :docker_image_url, :version,
             :tags, :status, :is_public, :env_schema, :cmd, :created_by,
             :workspace_id, now(), now())"""
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

    servers = data.get("servers", [])
    if not servers:
        print("⚠️  Registry contains no servers")
        return

    print(f"Found {len(servers)} servers in registry")

    inserted = 0
    try:
        with engine.begin() as conn:
            for entry in servers:
                try:
                    if upsert_registry_server(conn, entry):
                        inserted += 1
                except Exception as e:
                    # Log and skip individual failures
                    rid = entry.get("registry_id", "?")
                    print(f"  ⚠️  Skipping {rid}: {e}")

        print(f"✅ Registry import complete: {inserted} new servers ({len(servers)} total in registry)")

    except Exception as e:
        print(f"❌ Error importing registry: {e}")
        raise


if __name__ == "__main__":
    main()
