from agentarea.common.base.service import BaseCrudService
from agentarea.common.events.broker import EventBroker
from agentarea.modules.llm.domain.events import LLMModelCreated, LLMModelDeleted, LLMModelUpdated
from agentarea.modules.llm.domain.models import LLMModel
from agentarea.modules.llm.infrastructure.llm_model_repository import LLMModelRepository


from uuid import UUID


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
            provider_id=provider,
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
                provider=model.provider_id,
                model_type=model.model_type,
            )
        )

        return model

    async def update_llm_model(
        self,
        id: UUID,
        name: str | None = None,
        description: str | None = None,
        provider: str | None = None,
        model_type: str | None = None,
        endpoint_url: str | None = None,
        context_window: str | None = None,
        is_public: bool | None = None,
        status: str | None = None,
    ) -> LLMModel | None:
        model = await self.get(id)
        if not model:
            return None

        if name is not None:
            model.name = name
        if description is not None:
            model.description = description
        if provider is not None:
            model.provider_id = provider
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
                provider=model.provider_id,
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
        status: str | None = None,
        is_public: bool | None = None,
        provider: str | None = None,
    ) -> list[LLMModel]:
        return await self.repository.list(
            status=status, is_public=is_public, provider=provider
        )