from agentarea_common.di.container import DIContainer
from agentarea_common.events.broker import EventBroker
from agentarea_common.infrastructure.secret_manager import BaseSecretManager

from agentarea_llm.application.embedding_service import EmbeddingService
from agentarea_llm.application.provider_service import ProviderService
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
from agentarea_llm.infrastructure.provider_config_repository import ProviderConfigRepository
from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository


def setup_llm_di(container: DIContainer) -> None:
    """Setup dependency injection for LLM package."""
    # Register repositories (assuming they need session/dependencies from common)
    # These would typically be registered in the main app's DI setup

    # Register provider service
    def create_provider_service() -> ProviderService:
        provider_spec_repo = container.get(ProviderSpecRepository)
        provider_config_repo = container.get(ProviderConfigRepository)
        model_spec_repo = container.get(ModelSpecRepository)
        model_instance_repo = container.get(ModelInstanceRepository)
        event_broker = container.get(EventBroker)
        secret_manager = container.get(BaseSecretManager)

        return ProviderService(
            provider_spec_repo=provider_spec_repo,
            provider_config_repo=provider_config_repo,
            model_spec_repo=model_spec_repo,
            model_instance_repo=model_instance_repo,
            event_broker=event_broker,
            secret_manager=secret_manager,
        )

    container.register_factory(ProviderService, create_provider_service)

    # Register embedding service
    def create_embedding_service() -> EmbeddingService:
        provider_service = container.get(ProviderService)
        return EmbeddingService(provider_service)

    container.register_factory(EmbeddingService, create_embedding_service)
