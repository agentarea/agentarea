import os
import yaml
import uuid
from typing import Dict, Any, Optional
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

# Adjust these as needed
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg2://user:password@localhost:5432/agentarea"
)
YAML_PATH = os.environ.get("LLM_PROVIDERS_YAML", "/app/llm/providers.yaml")

engine = create_engine(DATABASE_URL)


def get_provider_type(provider_key: str) -> str:
    """Convert provider key to provider type for LiteLLM."""
    # Special case for ollama - LiteLLM expects "ollama_chat"
    if provider_key == "ollama":
        return "ollama_chat"
    # For most providers, the YAML key matches the LiteLLM provider key
    return provider_key


def upsert_provider_spec(
    conn: Connection,
    provider_key: str,
    provider_data: Dict[str, Any],
    is_builtin: bool = True,
) -> str:
    """Upsert provider specification"""
    # Use the predefined ID from YAML if available, otherwise generate one
    provider_id: Optional[str] = provider_data.get("id")
    if not provider_id:
        provider_id = str(uuid.uuid4())

    provider_name: str = provider_data.get("name", provider_key)
    description: Optional[str] = provider_data.get("description")
    icon: Optional[str] = provider_data.get("icon")
    
    # Use YAML provider key with minimal mapping
    provider_type = get_provider_type(provider_key)

    # Check if provider spec already exists by provider_key
    result = conn.execute(
        text("SELECT id FROM provider_specs WHERE provider_key = :provider_key"), 
        {"provider_key": provider_key}
    ).fetchone()
    
    if result:
        # Update existing provider spec
        existing_id = result[0]
        conn.execute(
            text("""
                UPDATE provider_specs 
                SET name = :name, description = :description, provider_type = :provider_type, 
                    icon = :icon, is_builtin = :is_builtin, updated_at = now() 
                WHERE provider_key = :provider_key
            """),
            {
                "name": provider_name,
                "description": description,
                "provider_type": provider_type,
                "icon": icon,
                "is_builtin": is_builtin,
                "provider_key": provider_key,
            },
        )
        return existing_id

    # Insert new provider spec
    conn.execute(
        text("""
            INSERT INTO provider_specs 
            (id, provider_key, name, description, provider_type, icon, is_builtin, created_by, workspace_id, created_at, updated_at) 
            VALUES (:id, :provider_key, :name, :description, :provider_type, :icon, :is_builtin, :created_by, :workspace_id, now(), now())
        """),
        {
            "id": provider_id,
            "provider_key": provider_key,
            "name": provider_name,
            "description": description,
            "provider_type": provider_type,
            "icon": icon,
            "is_builtin": is_builtin,
            "created_by": "system",
            "workspace_id": "system",
        },
    )
    return provider_id


def upsert_model_spec(
    conn: Connection, 
    model: Dict[str, Any], 
    provider_spec_id: str
) -> str:
    """Upsert model specification"""
    model_name = model["name"]
    display_name = model.get("display_name", model_name)
    description = model.get("description", "")
    context_window = model.get("context_window", 4096)
    
    # Check if model spec already exists
    result = conn.execute(
        text("""
            SELECT id FROM model_specs 
            WHERE provider_spec_id = :provider_spec_id AND model_name = :model_name
        """),
        {"provider_spec_id": provider_spec_id, "model_name": model_name},
    ).fetchone()
    
    if result:
        # Update existing model spec
        existing_id = result[0]
        conn.execute(
            text("""
                UPDATE model_specs 
                SET display_name = :display_name, description = :description, 
                    context_window = :context_window, updated_at = now()
                WHERE id = :id
            """),
            {
                "id": existing_id,
                "display_name": display_name,
                "description": description,
                "context_window": context_window,
            },
        )
        return existing_id
    
    # Insert new model spec
    model_spec_id = str(uuid.uuid4())
    conn.execute(
        text("""
            INSERT INTO model_specs
            (id, provider_spec_id, model_name, display_name, description, context_window, 
             is_active, created_by, workspace_id, created_at, updated_at)
            VALUES (:id, :provider_spec_id, :model_name, :display_name, :description, 
                    :context_window, true, :created_by, :workspace_id, now(), now())
        """),
        {
            "id": model_spec_id,
            "provider_spec_id": provider_spec_id,
            "model_name": model_name,
            "display_name": display_name,
            "description": description,
            "context_window": context_window,
            "created_by": "system",
            "workspace_id": "system",
        },
    )
    return model_spec_id


def main() -> None:
    """Main function to populate provider specs and model specs from YAML"""
    with open(YAML_PATH) as f:
        data = yaml.safe_load(f)
    
    providers = data.get("providers", {})
    
    with engine.begin() as conn:
        for provider_key, provider_data in providers.items():
            # Create/update provider spec
            provider_spec_id = upsert_provider_spec(conn, provider_key, provider_data)
            
            # Create/update model specs for this provider
            for model in provider_data.get("models", []):
                upsert_model_spec(conn, model, provider_spec_id)
    
    print("Provider specs and model specs populated successfully.")


if __name__ == "__main__":
    main() 