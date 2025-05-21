import os
import yaml
import uuid
from sqlalchemy import create_engine, text

# Adjust these as needed
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg2://user:password@localhost:5432/agentarea")
YAML_PATH = os.environ.get("LLM_PROVIDERS_YAML", os.path.join(os.path.dirname(__file__), "providers.yaml"))

engine = create_engine(DATABASE_URL)

def upsert_provider(conn, name, description=None, is_builtin=True):
    result = conn.execute(text("SELECT id FROM llm_providers WHERE name = :name"), {"name": name}).fetchone()
    if result:
        return result[0]
    provider_id = str(uuid.uuid4())
    conn.execute(
        text("INSERT INTO llm_providers (id, name, description, is_builtin, created_at, updated_at) VALUES (:id, :name, :description, :is_builtin, now(), now())"),
        {"id": provider_id, "name": name, "description": description, "is_builtin": is_builtin}
    )
    return provider_id

def upsert_model(conn, model, provider_id):
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

def main():
    with open(YAML_PATH) as f:
        data = yaml.safe_load(f)
    providers = data.get("providers", {})
    with engine.begin() as conn:
        for provider_key, provider_data in providers.items():
            provider_id = upsert_provider(conn, provider_key, provider_data.get("name", provider_key))
            for model in provider_data.get("models", []):
                upsert_model(conn, model, provider_id)
    print("Providers and models populated.")

if __name__ == "__main__":
    main() 