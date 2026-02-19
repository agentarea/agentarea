import os
import json
import yaml
import uuid
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from pydantic import BaseModel, Field, ValidationError

# Import schemas from platform code (single source of truth)
from agentarea_agents.schemas.import_export import (
    AgentYAML as AgentConfig,
    ToolConfigYAML as ToolConfig,
)

# Database connection
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg2://user:password@localhost:5432/agentarea"
)
AGENTS_YAML = os.environ.get(
    "AGENTS_YAML", "/app/bootstrap/agents.yaml"
)

engine = create_engine(DATABASE_URL)


# Root structure for agents YAML file
class AgentsYAML(BaseModel):
    """Root structure for agents YAML file."""
    agents: list[AgentConfig] = Field(default_factory=list)


def upsert_default_agent(conn: Connection, agent_config: AgentConfig) -> str:
    """Create or update the default system agent.

    Args:
        conn: Database connection
        agent_config: Validated agent configuration

    Returns:
        Agent ID (UUID as string)
    """
    agent_id = agent_config.id or str(uuid.uuid4())
    name = agent_config.name
    description = agent_config.description
    instruction = agent_config.instruction

    # Convert Pydantic models to JSON-serializable dict
    tools = [tool.model_dump(exclude_none=True) for tool in agent_config.tools] if agent_config.tools else []

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
                    instruction = :instruction, tools = :tools,
                    updated_at = now()
                WHERE id = :id
            """),
            {
                "id": agent_id,
                "name": name,
                "description": description,
                "instruction": instruction,
                "tools": json.dumps(tools),
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
             tools, events_config, planning,
             created_by, workspace_id, created_at, updated_at)
            VALUES (:id, :name, 'active', :description, :instruction, NULL,
                    :tools, NULL, false,
                    'system', 'system', now(), now())
        """),
        {
            "id": agent_id,
            "name": name,
            "description": description,
            "instruction": instruction,
            "tools": json.dumps(tools),
        },
    )
    print(f"  ✓ Created new default agent (ID: {agent_id})")
    return agent_id


def main() -> None:
    """Main function to populate system agents from YAML"""

    # Try multiple paths for YAML file
    yaml_paths = [
        AGENTS_YAML,
        "data/agents.yaml",
        "agentarea-bootstrap/data/agents.yaml",
        "/app/data/agents.yaml",
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
        print("⚠️  Agents YAML file not found in any location")
        print("   Checked paths:")
        for path in yaml_paths:
            print(f"   - {path}")
        print("   Skipping agents population")
        return

    print(f"  ✓ Found agents YAML at: {used_path}")

    # Validate YAML structure with Pydantic
    try:
        agents_config = AgentsYAML(**yaml_data)
    except ValidationError as e:
        print(f"❌ Invalid agents YAML format:")
        for error in e.errors():
            field = " -> ".join(str(x) for x in error["loc"])
            print(f"   {field}: {error['msg']}")
        raise

    if not agents_config.agents:
        print("⚠️  No agents found in YAML file")
        return

    try:
        with engine.begin() as conn:
            created_count = 0
            updated_count = 0

            for agent_config in agents_config.agents:
                # Check if agent already exists
                agent_id = agent_config.id or str(uuid.uuid4())
                result = conn.execute(
                    text("SELECT id FROM agents WHERE id = :id"),
                    {"id": agent_id}
                ).fetchone()

                if result:
                    updated_count += 1
                else:
                    created_count += 1

                upsert_default_agent(conn, agent_config)

        print(f"  ✓ Successfully populated {len(agents_config.agents)} agent(s)")
        print(f"    Created: {created_count}, Updated: {updated_count}")

    except Exception as e:
        print(f"❌ Error populating agents: {e}")
        raise


if __name__ == "__main__":
    main()
