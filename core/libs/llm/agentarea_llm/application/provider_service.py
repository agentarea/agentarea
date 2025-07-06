from uuid import UUID

from agentarea_common.base.service import BaseCrudService
from agentarea_common.events.broker import EventBroker
from agentarea_common.infrastructure.secret_manager import BaseSecretManager

from agentarea_llm.domain.models import ProviderSpec, ProviderConfig, ModelSpec, ModelInstance
from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository
from agentarea_llm.infrastructure.provider_config_repository import ProviderConfigRepository
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository


class ProviderService:
    """Service for managing providers in the new 4-entity architecture"""
    
    def __init__(
        self,
        provider_spec_repo: ProviderSpecRepository,
        provider_config_repo: ProviderConfigRepository,
        model_spec_repo: ModelSpecRepository,
        model_instance_repo: ModelInstanceRepository,
        event_broker: EventBroker,
        secret_manager: BaseSecretManager,
    ):
        self.provider_spec_repo = provider_spec_repo
        self.provider_config_repo = provider_config_repo
        self.model_spec_repo = model_spec_repo
        self.model_instance_repo = model_instance_repo
        self.event_broker = event_broker
        self.secret_manager = secret_manager

    # Provider Specs methods
    async def list_provider_specs(self, is_builtin: bool | None = None) -> list[ProviderSpec]:
        """List all available provider specifications"""
        return await self.provider_spec_repo.list(is_builtin=is_builtin)

    async def get_provider_spec(self, provider_spec_id: UUID) -> ProviderSpec | None:
        """Get provider spec by ID"""
        return await self.provider_spec_repo.get(provider_spec_id)

    async def get_provider_spec_by_key(self, provider_key: str) -> ProviderSpec | None:
        """Get provider spec by provider key (e.g., 'openai')"""
        return await self.provider_spec_repo.get_by_provider_key(provider_key)

    # Provider Configs methods
    async def create_provider_config(
        self,
        provider_spec_id: UUID,
        name: str,
        api_key: str,
        endpoint_url: str | None = None,
        user_id: UUID | None = None,
        is_public: bool = False,
    ) -> ProviderConfig:
        """Create a new provider configuration"""
        config = ProviderConfig(
            provider_spec_id=provider_spec_id,
            name=name,
            api_key=api_key,
            endpoint_url=endpoint_url,
            user_id=user_id,
            is_public=is_public,
        )
        
        # Store API key in secret manager
        secret_name = f"provider_config_{config.id}"
        await self.secret_manager.set_secret(secret_name, api_key)
        
        return await self.provider_config_repo.create(config)

    async def list_provider_configs(
        self,
        provider_spec_id: UUID | None = None,
        user_id: UUID | None = None,
        is_active: bool | None = None,
    ) -> list[ProviderConfig]:
        """List provider configurations"""
        return await self.provider_config_repo.list(
            provider_spec_id=provider_spec_id,
            user_id=user_id,
            is_active=is_active,
        )

    async def get_provider_config(self, config_id: UUID) -> ProviderConfig | None:
        """Get provider config by ID"""
        return await self.provider_config_repo.get(config_id)

    async def update_provider_config(
        self,
        config_id: UUID,
        name: str | None = None,
        api_key: str | None = None,
        endpoint_url: str | None = None,
        is_active: bool | None = None,
    ) -> ProviderConfig | None:
        """Update provider configuration"""
        config = await self.provider_config_repo.get(config_id)
        if not config:
            return None

        if name is not None:
            config.name = name
        if api_key is not None:
            config.api_key = api_key
            # Update secret
            secret_name = f"provider_config_{config.id}"
            await self.secret_manager.set_secret(secret_name, api_key)
        if endpoint_url is not None:
            config.endpoint_url = endpoint_url
        if is_active is not None:
            config.is_active = is_active

        return await self.provider_config_repo.update(config)

    async def delete_provider_config(self, config_id: UUID) -> bool:
        """Delete provider configuration"""
        # Clean up secret
        secret_name = f"provider_config_{config_id}"
        try:
            await self.secret_manager.delete_secret(secret_name)
        except Exception:
            pass  # Secret might not exist
        
        return await self.provider_config_repo.delete(config_id)

    # Model Specs methods
    async def list_model_specs(self, provider_spec_id: UUID | None = None) -> list[ModelSpec]:
        """List model specifications"""
        return await self.model_spec_repo.list(provider_spec_id=provider_spec_id)

    async def get_model_spec(self, model_spec_id: UUID) -> ModelSpec | None:
        """Get model spec by ID"""
        return await self.model_spec_repo.get(model_spec_id)

    # Model Instances methods
    async def create_model_instance(
        self,
        provider_config_id: UUID,
        model_spec_id: UUID,
        name: str,
        description: str | None = None,
        is_public: bool = False,
    ) -> ModelInstance:
        """Create a new model instance"""
        instance = ModelInstance(
            provider_config_id=provider_config_id,
            model_spec_id=model_spec_id,
            name=name,
            description=description,
            is_public=is_public,
        )
        return await self.model_instance_repo.create(instance)

    async def list_model_instances(
        self,
        provider_config_id: UUID | None = None,
        model_spec_id: UUID | None = None,
        is_active: bool | None = None,
    ) -> list[ModelInstance]:
        """List model instances"""
        return await self.model_instance_repo.list(
            provider_config_id=provider_config_id,
            model_spec_id=model_spec_id,
            is_active=is_active,
        )

    async def get_model_instance(self, instance_id: UUID) -> ModelInstance | None:
        """Get model instance by ID"""
        return await self.model_instance_repo.get(instance_id)

    async def delete_model_instance(self, instance_id: UUID) -> bool:
        """Delete model instance"""
        return await self.model_instance_repo.delete(instance_id)

    # Helper methods
    async def get_model_instance_with_config(self, instance_id: UUID) -> dict | None:
        """Get model instance with full provider configuration for LLM usage"""
        instance = await self.model_instance_repo.get(instance_id)
        if not instance:
            return None

        # Get API key from secret manager
        secret_name = f"provider_config_{instance.provider_config.id}"
        api_key = await self.secret_manager.get_secret(secret_name)

        return {
            "instance": instance,
            "provider_type": instance.provider_config.provider_spec.provider_type,
            "model_name": instance.model_spec.model_name,
            "api_key": api_key,
            "endpoint_url": instance.provider_config.endpoint_url,
        } 