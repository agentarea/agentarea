from pydantic_settings import BaseSettings


class ContextConfig(BaseSettings):
    provider: str = "faiss"
    embedding_model_instance_id: str | None = None  # UUID of ModelInstance for embeddings
    faiss_index_path: str = "./data/context_index.faiss"
    faiss_metadata_path: str = "./data/context_metadata.json"
    max_context_length: int = 1000

    class Config:
        """Configuration for ContextConfig."""

        env_prefix = "CONTEXT_"
