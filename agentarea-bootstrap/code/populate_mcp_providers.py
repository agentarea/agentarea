import os
import yaml
import json
import uuid
from typing import Dict, Any, Optional, List
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

# Adjust these as needed
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg2://user:password@localhost:5432/agentarea"
)
MCP_PROVIDERS_YAML = os.environ.get("MCP_PROVIDERS_YAML", "/app/llm/mcp_providers.yaml")

engine = create_engine(DATABASE_URL)


def upsert_mcp_server(
    conn: Connection, provider_key: str, provider_data: Dict[str, Any]
) -> str:
    """Create or update MCP server specification from provider data."""

    # Use the predefined ID from YAML if available, otherwise generate one
    server_id: Optional[str] = provider_data.get("id")
    if not server_id:
        server_id = str(uuid.uuid4())

    server_name: str = provider_data.get("name", provider_key)
    description: str = provider_data.get("description", "")
    docker_image_url: str = provider_data.get("docker_image", "")
    env_schema: List[Dict[str, Any]] = provider_data.get("env_vars", [])

    # Check if server already exists by ID
    result = conn.execute(
        text("SELECT id FROM mcp_servers WHERE id = :id"), {"id": server_id}
    ).fetchone()

    if result:
        # Update existing server
        conn.execute(
            text("""UPDATE mcp_servers
                    SET name = :name, description = :description,
                        docker_image_url = :docker_image_url,
                        env_schema = :env_schema, updated_at = now()
                    WHERE id = :id"""),
            {
                "id": server_id,
                "name": server_name,
                "description": description,
                "docker_image_url": docker_image_url,
                "env_schema": json.dumps(env_schema),  # Store as JSON string
            },
        )
        return server_id

    # Check if server exists by name (for migration purposes)
    result = conn.execute(
        text("SELECT id FROM mcp_servers WHERE name = :name"), {"name": server_name}
    ).fetchone()

    if result:
        existing_id = result[0]
        if str(existing_id) != server_id:
            # Update existing server with new ID
            conn.execute(
                text("""UPDATE mcp_servers
                        SET id = :new_id, description = :description,
                            docker_image_url = :docker_image_url,
                            env_schema = :env_schema, updated_at = now()
                        WHERE id = :old_id"""),
                {
                    "new_id": server_id,
                    "old_id": existing_id,
                    "description": description,
                    "docker_image_url": docker_image_url,
                    "env_schema": json.dumps(env_schema),
                },
            )
        return server_id

    # Insert new server
    # NOTE: Using "system" for workspace_id and created_by is intentional for
    # bootstrap/system-level data.
    # These are built-in MCP server specs available to all workspaces, created
    # during system initialization before any users/workspaces exist. This is
    # acceptable for bootstrap scripts.
    conn.execute(
        text("""INSERT INTO mcp_servers
                (id, name, description, docker_image_url, version, tags,
                 status, is_public, env_schema, created_by, workspace_id,
                 created_at, updated_at)
                VALUES
                (:id, :name, :description, :docker_image_url, :version,
                 :tags, :status, :is_public, :env_schema, :created_by,
                 :workspace_id, now(), now())"""),
        {
            "id": server_id,
            "name": server_name,
            "description": description,
            "docker_image_url": docker_image_url,
            "version": "latest",
            "tags": json.dumps([provider_key]),  # Store provider key as tag
            "status": "active",
            "is_public": True,
            "env_schema": json.dumps(env_schema),
            "created_by": "system",  # Intentional: system-level bootstrap data
            "workspace_id": "system",  # Intentional: system-level bootstrap data
        },
    )
    return server_id


def main() -> None:
    """Main function to populate MCP servers from YAML configuration."""
    print("Loading MCP providers from:", MCP_PROVIDERS_YAML)

    # Try to find the YAML file in multiple locations
    yaml_paths = [
        MCP_PROVIDERS_YAML,
        "data/mcp_providers.yaml",  # local development
        "agentarea-bootstrap/data/mcp_providers.yaml",  # alternative path
    ]

    yaml_data = None
    used_path = None

    for path in yaml_paths:
        try:
            with open(path) as f:
                yaml_data = yaml.safe_load(f)
                used_path = path
                break
        except FileNotFoundError:
            continue

    if yaml_data is None:
        print("❌ MCP providers YAML file not found in any of these locations:")
        for path in yaml_paths:
            print(f"   - {path}")
        return

    print(f"✓ Found MCP providers YAML at: {used_path}")

    data = yaml_data
    providers = data.get("providers", {})
    if not providers:
        print("⚠️  No MCP providers found in YAML file")
        return

    print(f"Found {len(providers)} MCP providers to process")

    try:
        with engine.begin() as conn:
            for provider_key, provider_data in providers.items():
                upsert_mcp_server(conn, provider_key, provider_data)

        print(f"✅ Successfully populated {len(providers)} MCP server specifications")

    except Exception as e:
        print(f"❌ Error populating MCP providers: {e}")
        raise


if __name__ == "__main__":
    main()
