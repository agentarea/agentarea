import os
import json
import yaml
import uuid
from typing import Dict, Any
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

# Database connection
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg2://user:password@localhost:5432/agentarea"
)
DEFAULT_AGENT_YAML = os.environ.get(
    "DEFAULT_AGENT_YAML", "/app/bootstrap/default_agent.yaml"
)

engine = create_engine(DATABASE_URL)


def upsert_default_agent(conn: Connection, agent_data: Dict[str, Any]) -> str:
    """Create or update the default system agent.

    Args:
        conn: Database connection
        agent_data: Agent configuration from YAML

    Returns:
        Agent ID (UUID as string)
    """
    agent_id = agent_data.get("id", str(uuid.uuid4()))
    name = agent_data.get("name", "Default Agent")
    description = agent_data.get("description", "")
    instruction = agent_data.get("instruction", "")
    tools_config = agent_data.get("tools_config", {})

    # Check if agent exists
    result = conn.execute(
        text("SELECT id FROM agents WHERE id = :id"),
        {"id": agent_id}
    ).fetchone()

    if result:
        # Update existing agent
        conn.execute(
            text("""
                UPDATE agents
                SET name = :name, description = :description,
                    instruction = :instruction, tools_config = :tools_config,
                    updated_at = now()
                WHERE id = :id
            """),
            {
                "id": agent_id,
                "name": name,
                "description": description,
                "instruction": instruction,
                "tools_config": json.dumps(tools_config),
            },
        )
        print(f"  ✓ Updated existing default agent (ID: {agent_id})")
        return agent_id

    # Insert new agent
    # NOTE: Using "system" for workspace_id and created_by is intentional
    # This is the system default agent available to all workspaces
    conn.execute(
        text("""
            INSERT INTO agents
            (id, name, status, description, instruction, model_id,
             tools_config, events_config, planning,
             created_by, workspace_id, created_at, updated_at)
            VALUES (:id, :name, 'active', :description, :instruction, NULL,
                    :tools_config, NULL, false,
                    'system', 'system', now(), now())
        """),
        {
            "id": agent_id,
            "name": name,
            "description": description,
            "instruction": instruction,
            "tools_config": json.dumps(tools_config),
        },
    )
    print(f"  ✓ Created new default agent (ID: {agent_id})")
    return agent_id


def main() -> None:
    """Main function to populate default agent from YAML"""

    # Try multiple paths for YAML file
    yaml_paths = [
        DEFAULT_AGENT_YAML,
        "data/default_agent.yaml",
        "agentarea-bootstrap/data/default_agent.yaml",
        "/app/data/default_agent.yaml",
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
        print("⚠️  Default agent YAML file not found in any location")
        print("   Checked paths:")
        for path in yaml_paths:
            print(f"   - {path}")
        print("   Skipping default agent population")
        return

    print(f"  ✓ Found default agent YAML at: {used_path}")

    agent_data = yaml_data.get("agent", {})
    if not agent_data:
        print("⚠️  No agent data found in YAML file")
        return

    try:
        with engine.begin() as conn:
            agent_id = upsert_default_agent(conn, agent_data)

        print(f"  ✓ Successfully populated default agent (ID: {agent_id})")

    except Exception as e:
        print(f"❌ Error populating default agent: {e}")
        raise


if __name__ == "__main__":
    main()
