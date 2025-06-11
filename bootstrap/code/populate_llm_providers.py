import os
import yaml
import uuid
from typing import Dict, Any, Optional
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

# Adjust these as needed
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg2://user:password@localhost:5432/agentarea")
YAML_PATH = os.environ.get("LLM_PROVIDERS_YAML", "/app/llm/providers.yaml")

engine = create_engine(DATABASE_URL)

def upsert_provider(conn: Connection, provider_key: str, provider_data: Dict[str, Any], is_builtin: bool = True) -> str:
    # Use the predefined ID from YAML if available, otherwise generate one
    provider_id: Optional[str] = provider_data.get("id")
    if not provider_id:
        provider_id = str(uuid.uuid4())
    
    provider_name: str = provider_data.get("name", provider_key)
    description: Optional[str] = provider_data.get("description")
    
    # Check if provider already exists by ID
    result = conn.execute(text("SELECT id FROM llm_providers WHERE id = :id"), {"id": provider_id}).fetchone()
    if result:
        # Update existing provider
        conn.execute(
            text("UPDATE llm_providers SET name = :name, description = :description, updated_at = now() WHERE id = :id"),
            {"id": provider_id, "name": provider_name, "description": description}
        )
        return provider_id
    
    # Check if provider exists by name (for migration purposes)
    result = conn.execute(text("SELECT id FROM llm_providers WHERE name = :name"), {"name": provider_name}).fetchone()
    if result:
        # Update existing provider with new ID if different
        existing_id = result[0]
        if existing_id != provider_id:
            conn.execute(
                text("UPDATE llm_providers SET id = :new_id, description = :description, updated_at = now() WHERE id = :old_id"),
                {"new_id": provider_id, "old_id": existing_id, "description": description}
            )
        return provider_id
    
    # Insert new provider
    conn.execute(
        text("INSERT INTO llm_providers (id, name, description, is_builtin, created_at, updated_at) VALUES (:id, :name, :description, :is_builtin, now(), now())"),
        {"id": provider_id, "name": provider_name, "description": description, "is_builtin": is_builtin}
    )
    return provider_id

def upsert_model(conn: Connection, model: Dict[str, Any], provider_id: str) -> str:
    result = conn.execute(
        text("SELECT id FROM llm_models WHERE name = :name AND provider_id = :provider_id"),
        {"name": model["name"], "provider_id": provider_id}
    ).fetchone()
    if result:
        return result[0]
    model_id = str(uuid.uuid4())
    conn.execute(
        text("""INSERT INTO llm_models
        (id, name, description, provider_id, model_type, endpoint_url, context_window, status, is_public, created_at, updated_at)
        VALUES
        (:id, :name, :description, :provider_id, :model_type, '', :context_window, 'active', true, now(), now())
        """),
        {
            "id": model_id,
            "name": model["name"],
            "description": model.get("description", ""),
            "provider_id": provider_id,
            "model_type": model["name"],
            "context_window": str(model.get("context_window", 0)),
        }
    )
    return model_id

def main() -> None:
    with open(YAML_PATH) as f:
        data = yaml.safe_load(f)
    providers = data.get("providers", {})
    with engine.begin() as conn:
        for provider_key, provider_data in providers.items():
            provider_id = upsert_provider(conn, provider_key, provider_data)
            for model in provider_data.get("models", []):
                upsert_model(conn, model, provider_id)
    print("Providers and models populated.")

if __name__ == "__main__":
    main() 