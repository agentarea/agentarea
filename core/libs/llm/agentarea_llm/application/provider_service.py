from typing import Any
from uuid import UUID

from agentarea_common.events.broker import EventBroker
from agentarea_common.infrastructure.secret_manager import BaseSecretManager

from agentarea_llm.domain.models import (
    ModelInstance,
    ModelSpec,
    ProviderConfig,
    ProviderSpec,
)
from agentarea_llm.infrastructure.model_instance_repository import (
    ModelInstanceRepository,
)
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
from agentarea_llm.infrastructure.provider_config_repository import (
    ProviderConfigRepository,
)
from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository


class ProviderService:
    """Service for managing provider specifications, configurations, model specifications,
    and model instances in the 4-entity architecture.

    This service coordinates repository access and secret management for provider-related entities.
    """

    def __init__(
        self,
        provider_spec_repo: ProviderSpecRepository,
        provider_config_repo: ProviderConfigRepository,
        model_spec_repo: ModelSpecRepository,
        model_instance_repo: ModelInstanceRepository,
        event_broker: EventBroker,
        secret_manager: BaseSecretManager,
    ):
        """Initialize the ProviderService.

        Args:
            provider_spec_repo (ProviderSpecRepository): Repository for provider specifications.
            provider_config_repo (ProviderConfigRepository): Repository for provider configurations.
            model_spec_repo (ModelSpecRepository): Repository for model specifications.
            model_instance_repo (ModelInstanceRepository): Repository for model instances.
            event_broker (EventBroker): Event broker for publishing events.
            secret_manager (BaseSecretManager): Secret manager for handling sensitive data.
        """
        self.provider_spec_repo = provider_spec_repo
        self.provider_config_repo = provider_config_repo
        self.model_spec_repo = model_spec_repo
        self.model_instance_repo = model_instance_repo
        self.event_broker = event_broker
        self.secret_manager = secret_manager

    # Provider Specs methods

    async def list_provider_specs(self, is_builtin: bool | None = None) -> list[ProviderSpec]:
        """List all available provider specifications.

        Args:
            is_builtin (Optional[bool]): Filter by built-in status.

        Returns:
            List[ProviderSpec]: List of provider specifications.
        """
        return await self.provider_spec_repo.list_specs(is_builtin=is_builtin)

    async def get_provider_spec(self, provider_spec_id: UUID) -> ProviderSpec | None:
        """Retrieve a provider specification by its ID.

        Args:
            provider_spec_id (UUID): The ID of the provider specification.

        Returns:
            Optional[ProviderSpec]: The provider specification if found, else None.
        """
        return await self.provider_spec_repo.get_by_id(provider_spec_id)

    async def get_provider_spec_by_key(self, provider_key: str) -> ProviderSpec | None:
        """Retrieve a provider specification by its provider key.

        Args:
            provider_key (str): The provider key (e.g., 'openai').

        Returns:
            Optional[ProviderSpec]: The provider specification if found, else None.
        """
        return await self.provider_spec_repo.get_by_provider_key(provider_key)

    # Provider Configs methods

    async def create_provider_config(
        self,
        provider_spec_id: UUID,
        name: str,
        api_key: str,
        endpoint_url: str | None = None,
        created_by: str | None = None,
        is_public: bool = False,
    ) -> ProviderConfig:
        """Create a new provider configuration and store its API key in the secret manager.

        Args:
            provider_spec_id (UUID): The provider specification ID.
            name (str): Name of the provider configuration.
            api_key (str): API key for the provider.
            endpoint_url (Optional[str]): Optional endpoint URL.
            created_by (Optional[str]): Optional user who created this config.
            is_public (bool): Whether the configuration is public.

        Returns:
            ProviderConfig: The created provider configuration.
        """
        config = ProviderConfig(
            provider_spec_id=provider_spec_id,
            name=name,
            endpoint_url=endpoint_url,
            created_by=created_by or "system",
            is_public=is_public,
        )
        secret_name = f"provider_config_{config.id}"
        config.api_key = secret_name
        await self.secret_manager.set_secret(secret_name, api_key)

        return await self.provider_config_repo.create_config(config)

    async def list_provider_configs(
        self,
        provider_spec_id: UUID | None = None,
        user_id: UUID | None = None,
        is_active: bool | None = None,
    ) -> list[ProviderConfig]:
        """List provider configurations with optional filtering.

        Args:
            provider_spec_id (Optional[UUID]): Filter by provider specification ID.
            user_id (Optional[UUID]): Filter by user ID.
            is_active (Optional[bool]): Filter by active status.

        Returns:
            List[ProviderConfig]: List of provider configurations.
        """
        return await self.provider_config_repo.list_configs(
            provider_spec_id=provider_spec_id,
            is_active=is_active,
        )

    async def get_provider_config(self, config_id: UUID) -> ProviderConfig | None:
        """Retrieve a provider configuration by its ID.

        Args:
            config_id (UUID): The configuration ID.

        Returns:
            Optional[ProviderConfig]: The provider configuration if found, else None.
        """
        return await self.provider_config_repo.get_with_relations(config_id)

    async def update_provider_config(
        self,
        config_id: UUID,
        name: str | None = None,
        api_key: str | None = None,
        endpoint_url: str | None = None,
        is_active: bool | None = None,
    ) -> ProviderConfig | None:
        """Update an existing provider configuration and update the secret if the API key changes.

        Args:
            config_id (UUID): The configuration ID.
            name (Optional[str]): New name.
            api_key (Optional[str]): New API key.
            endpoint_url (Optional[str]): New endpoint URL.
            is_active (Optional[bool]): New active status.

        Returns:
            Optional[ProviderConfig]: The updated provider configuration if found, else None.
        """
        config = await self.provider_config_repo.get_by_id(config_id)
        if not config:
            return None

        if name is not None:
            config.name = name
        if api_key is not None:
            config.api_key = api_key
            secret_name = f"provider_config_{config.id}"
            await self.secret_manager.set_secret(secret_name, api_key)
        if endpoint_url is not None:
            config.endpoint_url = endpoint_url
        if is_active is not None:
            config.is_active = is_active

        return await self.provider_config_repo.update_config(config)

    async def delete_provider_config(self, config_id: UUID) -> bool:
        """Delete a provider configuration and remove its API key from the secret manager.

        Args:
            config_id (UUID): The configuration ID.

        Returns:
            bool: True if deleted, False otherwise.
        """
        secret_name = f"provider_config_{config_id}"
        try:
            await self.secret_manager.delete_secret(secret_name)
        except Exception:  # noqa: S110
            pass

        return await self.provider_config_repo.delete(config_id)

    # Model Specs methods

    async def list_model_specs(self, provider_spec_id: UUID | None = None) -> list[ModelSpec]:
        """List model specifications with optional filtering by provider specification.

        Args:
            provider_spec_id (Optional[UUID]): Filter by provider specification ID.

        Returns:
            List[ModelSpec]: List of model specifications.
        """
        return await self.model_spec_repo.list_specs(provider_spec_id=provider_spec_id)

    async def get_model_spec(self, model_spec_id: UUID) -> ModelSpec | None:
        """Retrieve a model specification by its ID.

        Args:
            model_spec_id (UUID): The model specification ID.

        Returns:
            Optional[ModelSpec]: The model specification if found, else None.
        """
        return await self.model_spec_repo.get_by_id(model_spec_id)

    # Model Instances methods

    async def create_model_instance(
        self,
        provider_config_id: UUID,
        model_spec_id: UUID,
        name: str,
        description: str | None = None,
        is_public: bool = False,
    ) -> ModelInstance:
        """Create a new model instance.

        Args:
            provider_config_id (UUID): The provider configuration ID.
            model_spec_id (UUID): The model specification ID.
            name (str): Name of the model instance.
            description (Optional[str]): Optional description.
            is_public (bool): Whether the instance is public.

        Returns:
            ModelInstance: The created model instance.
        """
        instance = ModelInstance(
            provider_config_id=provider_config_id,
            model_spec_id=model_spec_id,
            name=name,
            description=description,
            is_public=is_public,
        )
        return await self.model_instance_repo.create_instance(instance)

    async def list_model_instances(
        self,
        provider_config_id: UUID | None = None,
        model_spec_id: UUID | None = None,
        is_active: bool | None = None,
    ) -> list[ModelInstance]:
        """List model instances with optional filtering.

        Args:
            provider_config_id (Optional[UUID]): Filter by provider configuration ID.
            model_spec_id (Optional[UUID]): Filter by model specification ID.
            is_active (Optional[bool]): Filter by active status.

        Returns:
            List[ModelInstance]: List of model instances.
        """
        return await self.model_instance_repo.list_instances(
            provider_config_id=provider_config_id,
            model_spec_id=model_spec_id,
            is_active=is_active,
        )

    async def get_model_instance(self, instance_id: UUID) -> ModelInstance | None:
        """Retrieve a model instance by its ID.

        Args:
            instance_id (UUID): The model instance ID.

        Returns:
            Optional[ModelInstance]: The model instance if found, else None.
        """
        return await self.model_instance_repo.get_with_relations(instance_id)

    async def delete_model_instance(self, instance_id: UUID) -> bool:
        """Delete a model instance.

        Args:
            instance_id (UUID): The model instance ID.

        Returns:
            bool: True if deleted, False otherwise.
        """
        return await self.model_instance_repo.delete(instance_id)

    # Helper methods

    async def get_model_instance_with_config(self, instance_id: UUID) -> dict[str, Any] | None:
        """Retrieve a model instance along with its provider configuration details and API key.

        Args:
            instance_id (UUID): The model instance ID.

        Returns:
            Optional[Dict[str, Any]]: Dictionary containing instance, provider type, model name,
                                      API key, and endpoint URL, or None if not found.
        """
        instance = await self.model_instance_repo.get_with_relations(instance_id)
        if not instance:
            return None

        secret_name = f"provider_config_{instance.provider_config.id}"
        api_key = await self.secret_manager.get_secret(secret_name)

        return {
            "instance": instance,
            "provider_type": instance.provider_config.provider_spec.provider_type,
            "model_name": instance.model_spec.model_name,
            "api_key": api_key,
            "endpoint_url": instance.provider_config.endpoint_url,
        }
