from uuid import UUID

import litellm

from agentarea_llm.application.provider_service import ProviderService


class EmbeddingService:
    """Service for generating embeddings using LiteLLM with AgentArea's model instances."""

    def __init__(self, provider_service: ProviderService):
        self.provider_service = provider_service

    async def generate_embeddings(
        self, texts: list[str], model_instance_id: UUID
    ) -> list[list[float]]:
        """Generate embeddings for a list of texts using the specified model instance."""
        # Get model instance details
        instance_details = await self.provider_service.get_model_instance_with_config(
            model_instance_id
        )

        if not instance_details:
            raise ValueError(f"Model instance {model_instance_id} not found")

        # Use LiteLLM to generate embeddings
        try:
            response = await litellm.aembedding(
                model=instance_details["model_name"],
                input=texts,
                api_key=instance_details["api_key"],
                base_url=instance_details["endpoint_url"],
            )

            return [embedding["embedding"] for embedding in response.data]

        except Exception as e:
            raise RuntimeError(f"Failed to generate embeddings: {e!s}") from e

    async def get_embedding_dimension(self, model_instance_id: UUID) -> int:
        """Get the dimension of embeddings for the specified model instance."""
        # For efficiency, we can generate a single embedding to get the dimension
        # Most models have known dimensions, but this is a reliable fallback
        try:
            embeddings = await self.generate_embeddings(["test"], model_instance_id)
            return len(embeddings[0])
        except Exception as e:
            # Fallback to common embedding dimensions
            instance_details = await self.provider_service.get_model_instance_with_config(
                model_instance_id
            )

            if not instance_details:
                raise ValueError(f"Model instance {model_instance_id} not found") from e

            # Common embedding dimensions by model name
            model_name = instance_details["model_name"]
            if "text-embedding-ada-002" in model_name:
                return 1536
            elif "text-embedding-3-small" in model_name:
                return 1536
            elif "text-embedding-3-large" in model_name:
                return 3072
            else:
                # Default dimension for unknown models
                return 1536
