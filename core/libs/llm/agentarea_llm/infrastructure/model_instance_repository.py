from uuid import UUID

from agentarea_common.base.repository import BaseRepository
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from agentarea_llm.domain.models import ModelInstance, ProviderConfig


class ModelInstanceRepository(BaseRepository[ModelInstance]):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, id: UUID) -> ModelInstance | None:
        result = await self.session.execute(
            select(ModelInstance)
            .options(
                joinedload(ModelInstance.provider_config).joinedload(ProviderConfig.provider_spec),
                joinedload(ModelInstance.model_spec)
            )
            .where(ModelInstance.id == id)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        provider_config_id: UUID | None = None,
        model_spec_id: UUID | None = None,
        is_active: bool | None = None,
        is_public: bool | None = None,
    ) -> list[ModelInstance]:
        query = select(ModelInstance).options(
            joinedload(ModelInstance.provider_config).joinedload(ProviderConfig.provider_spec),
            joinedload(ModelInstance.model_spec)
        )

        conditions = []
        if provider_config_id is not None:
            conditions.append(ModelInstance.provider_config_id == provider_config_id)
        if model_spec_id is not None:
            conditions.append(ModelInstance.model_spec_id == model_spec_id)
        if is_active is not None:
            conditions.append(ModelInstance.is_active == is_active)
        if is_public is not None:
            conditions.append(ModelInstance.is_public == is_public)

        if conditions:
            query = query.where(and_(*conditions))

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create(self, entity: ModelInstance) -> ModelInstance:
        self.session.add(entity)
        await self.session.flush()
        # Reload with relationships
        result = await self.get(UUID(str(entity.id)))
        return result if result else entity

    async def update(self, entity: ModelInstance) -> ModelInstance:
        await self.session.merge(entity)
        await self.session.flush()
        return entity

    async def delete(self, id: UUID) -> bool:
        result = await self.session.execute(select(ModelInstance).where(ModelInstance.id == id))
        instance = result.scalar_one_or_none()
        if instance:
            await self.session.delete(instance)
            await self.session.flush()
            return True
        return False 