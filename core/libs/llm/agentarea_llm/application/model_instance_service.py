from uuid import UUID

from agentarea_common.base.service import BaseCrudService
from agentarea_common.events.broker import EventBroker
from agentarea_common.infrastructure.secret_manager import BaseSecretManager

from agentarea_llm.domain.models import ModelInstance
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository


class ModelInstanceService(BaseCrudService[ModelInstance]):
    """Service for managing ModelInstance in the new 4-entity architecture."""

    def __init__(
        self,
        repository: ModelInstanceRepository,
        event_broker: EventBroker,
        secret_manager: BaseSecretManager,
    ):
        super().__init__(repository)
        self.repository = repository
        self.event_broker = event_broker
        self.secret_manager = secret_manager

    async def get(self, id: UUID) -> ModelInstance | None:
        """Get ModelInstance with all relationships loaded."""
        return await self.repository.get_with_relations(id)

    async def list(
        self,
        provider_config_id: UUID | None = None,
        model_spec_id: UUID | None = None,
        is_active: bool | None = None,
        is_public: bool | None = None,
    ) -> list[ModelInstance]:
        """List ModelInstances with filtering options."""
        return await self.repository.list(
            provider_config_id=provider_config_id,
            model_spec_id=model_spec_id,
            is_active=is_active,
            is_public=is_public,
        )

    async def create_model_instance(
        self,
        provider_config_id: UUID,
        model_spec_id: UUID,
        name: str,
        description: str | None = None,
        is_public: bool = False,
    ) -> ModelInstance:
        """Create a new ModelInstance."""
        instance = ModelInstance(
            provider_config_id=str(provider_config_id),
            model_spec_id=str(model_spec_id),
            name=name,
            description=description,
            is_public=is_public,
        )

        instance = await self.create(instance)

        # TODO: Add event publishing when events are defined for new architecture
        # await self.event_broker.publish(ModelInstanceCreated(...))

        return instance

    async def update_model_instance(
        self,
        id: UUID,
        name: str | None = None,
        description: str | None = None,
        is_active: bool | None = None,
        is_public: bool | None = None,
    ) -> ModelInstance | None:
        """Update a ModelInstance."""
        instance = await self.get(id)
        if not instance:
            return None

        if name is not None:
            instance.name = name
        if description is not None:
            instance.description = description
        if is_active is not None:
            instance.is_active = is_active
        if is_public is not None:
            instance.is_public = is_public

        instance = await self.update(instance)

        # TODO: Add event publishing when events are defined for new architecture
        # await self.event_broker.publish(ModelInstanceUpdated(...))

        return instance

    async def delete_model_instance(self, id: UUID) -> bool:
        """Delete a ModelInstance."""
        success = await self.delete(id)
        if success:
            # TODO: Add event publishing when events are defined for new architecture
            # await self.event_broker.publish(ModelInstanceDeleted(instance_id=id))
            pass
        return success
