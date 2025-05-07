from typing import List, Optional
from uuid import UUID

from agentarea.common.base.service import BaseCrudService
from agentarea.common.events.broker import EventBroker
from ..infrastructure.llm_model_instance_repository import LLMModelInstanceRepository

from ..domain.events import (
    LLMModelCreated,
    LLMModelDeleted,
    LLMModelInstanceCreated,
    LLMModelInstanceDeleted,
    LLMModelInstanceUpdated,
    LLMModelUpdated,
)
from ..domain.models import LLMModel, LLMModelInstance
from ..infrastructure.llm_model_repository import LLMModelRepository


class LLMModelService(BaseCrudService[LLMModel]):
    def __init__(self, repository: LLMModelRepository, event_broker: EventBroker):
        super().__init__(repository)
        self.event_broker = event_broker

    async def create_llm_model(
        self,
        name: str,
        description: str,
        provider: str,
        model_type: str,
        endpoint_url: str,
        context_window: str,
        is_public: bool = False,
    ) -> LLMModel:
        model = LLMModel(
            name=name,
            description=description,
            provider=provider,
            model_type=model_type,
            endpoint_url=endpoint_url,
            context_window=context_window,
            is_public=is_public,
        )
        model = await self.create(model)

        await self.event_broker.publish(
            LLMModelCreated(
                model_id=model.id,
                name=model.name,
                provider=model.provider,
                model_type=model.model_type,
            )
        )

        return model

    async def update_llm_model(
        self,
        id: UUID,
        name: Optional[str] = None,
        description: Optional[str] = None,
        provider: Optional[str] = None,
        model_type: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        context_window: Optional[str] = None,
        is_public: Optional[bool] = None,
        status: Optional[str] = None,
    ) -> Optional[LLMModel]:
        model = await self.get(id)
        if not model:
            return None

        if name is not None:
            model.name = name
        if description is not None:
            model.description = description
        if provider is not None:
            model.provider = provider
        if model_type is not None:
            model.model_type = model_type
        if endpoint_url is not None:
            model.endpoint_url = endpoint_url
        if context_window is not None:
            model.context_window = context_window
        if is_public is not None:
            model.is_public = is_public
        if status is not None:
            model.status = status

        model = await self.update(model)

        await self.event_broker.publish(
            LLMModelUpdated(
                model_id=model.id,
                name=model.name,
                provider=model.provider,
                model_type=model.model_type,
            )
        )

        return model

    async def delete_llm_model(self, id: UUID) -> bool:
        success = await self.delete(id)
        if success:
            await self.event_broker.publish(LLMModelDeleted(model_id=id))
        return success

    async def list(
        self,
        status: Optional[str] = None,
        is_public: Optional[bool] = None,
        provider: Optional[str] = None,
    ) -> List[LLMModel]:
        return await self.repository.list(
            status=status, is_public=is_public, provider=provider
        )


class LLMModelInstanceService(BaseCrudService[LLMModelInstance]):
    def __init__(
        self, repository: LLMModelInstanceRepository, event_broker: EventBroker
    ):
        super().__init__(repository)
        self.event_broker = event_broker

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
        name: Optional[str] = None,
        description: Optional[str] = None,
        api_key: Optional[str] = None,
        is_public: Optional[bool] = None,
        status: Optional[str] = None,
    ) -> Optional[LLMModelInstance]:
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
        model_id: Optional[UUID] = None,
        status: Optional[str] = None,
        is_public: Optional[bool] = None,
    ) -> List[LLMModelInstance]:
        return await self.repository.list(
            model_id=model_id, status=status, is_public=is_public
        )
