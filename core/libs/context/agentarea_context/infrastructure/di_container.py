from uuid import UUID

from agentarea_common.di.container import DIContainer
from agentarea_llm.application.embedding_service import EmbeddingService

from agentarea_context.application.context_service import ContextService
from agentarea_context.config.context_config import ContextConfig
from agentarea_context.domain.interfaces import ContextProvider
from agentarea_context.infrastructure.providers.faiss_provider import FAISSContextProvider


def setup_context_di(container: DIContainer) -> None:
    """Setup dependency injection for context package."""
    # Register configuration
    config = ContextConfig()
    container.register_singleton(ContextConfig, config)

    # Register provider based on configuration
    def create_context_provider() -> ContextProvider:
        embedding_service = container.get(EmbeddingService)

        if not config.embedding_model_instance_id:
            raise ValueError("CONTEXT_EMBEDDING_MODEL_INSTANCE_ID must be set")

        model_instance_id = UUID(config.embedding_model_instance_id)

        if config.provider == "faiss":
            return FAISSContextProvider(config, embedding_service, model_instance_id)
        else:
            raise ValueError(f"Unsupported context provider: {config.provider}")

    container.register_factory(ContextProvider, create_context_provider)

    # Register service
    def create_context_service() -> ContextService:
        provider = container.get(ContextProvider)
        return ContextService(provider)

    container.register_factory(ContextService, create_context_service)
