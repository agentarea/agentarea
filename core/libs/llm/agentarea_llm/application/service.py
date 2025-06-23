from uuid import UUID

from agentarea_common.base.service import BaseCrudService
from agentarea_common.config import get_database
from agentarea_common.events.broker import EventBroker
from agentarea_common.infrastructure.secret_manager import BaseSecretManager

from agentarea_llm.domain.events import (
    LLMModelInstanceCreated,
    LLMModelInstanceDeleted,
    LLMModelInstanceUpdated,
)
from agentarea_llm.domain.models import LLMModelInstance
from agentarea_llm.infrastructure.llm_model_instance_repository import LLMModelInstanceRepository


class LLMModelInstanceService(BaseCrudService[LLMModelInstance]):
    def __init__(
        self,
        repository: LLMModelInstanceRepository,
        event_broker: EventBroker,
        secret_manager: BaseSecretManager,
    ):
        self.repository = repository
        self.event_broker = event_broker
        self.secret_manager = secret_manager
        self.db = get_database()  # Add database access

    async def create_llm_model_instance(
        self,
        model_id: UUID,
        api_key: str,
        name: str,
        description: str,
        is_public: bool = False,
    ) -> LLMModelInstance:
        instance = LLMModelInstance(
            model_id=model_id,
            api_key=api_key,
            name=name,
            description=description,
            is_public=is_public,
        )
        secret_name = f"llm_model_instance_{instance.id}"
        await self.secret_manager.set_secret(secret_name, api_key)

        instance = await self.create(instance)

        await self.event_broker.publish(
            LLMModelInstanceCreated(
                instance_id=instance.id, model_id=instance.model_id, name=instance.name
            )
        )

        return instance

    async def update_llm_model_instance(
        self,
        id: UUID,
        name: str | None = None,
        description: str | None = None,
        api_key: str | None = None,
        is_public: bool | None = None,
        status: str | None = None,
    ) -> LLMModelInstance | None:
        instance = await self.get(id)
        if not instance:
            return None

        if name is not None:
            instance.name = name
        if description is not None:
            instance.description = description
        if api_key is not None:
            instance.api_key = api_key
        if is_public is not None:
            instance.is_public = is_public
        if status is not None:
            instance.status = status

        instance = await self.update(instance)

        await self.event_broker.publish(
            LLMModelInstanceUpdated(
                instance_id=instance.id, model_id=instance.model_id, name=instance.name
            )
        )

        return instance

    async def delete_llm_model_instance(self, id: UUID) -> bool:
        success = await self.delete(id)
        if success:
            await self.event_broker.publish(LLMModelInstanceDeleted(instance_id=id))
        return success

    async def list(
        self,
        model_id: UUID | None = None,
        status: str | None = None,
        is_public: bool | None = None,
    ) -> list[LLMModelInstance]:
        return await self.repository.list(model_id=model_id, status=status, is_public=is_public)

    async def get(self, id: UUID) -> LLMModelInstance | None:
        """Get LLM model instance with separate session to avoid transaction conflicts."""
        async with self.db.get_db() as session:
            repo = LLMModelInstanceRepository(session)
            return await repo.get(id)
