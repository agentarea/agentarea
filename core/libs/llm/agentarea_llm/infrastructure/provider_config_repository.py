from uuid import UUID

from agentarea_common.base.repository import BaseRepository
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from agentarea_llm.domain.models import ProviderConfig


class ProviderConfigRepository(BaseRepository[ProviderConfig]):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, id: UUID) -> ProviderConfig | None:
        result = await self.session.execute(
            select(ProviderConfig)
            .options(
                joinedload(ProviderConfig.provider_spec),
                selectinload(ProviderConfig.model_instances)
            )
            .where(ProviderConfig.id == id)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        provider_spec_id: UUID | None = None,
        user_id: UUID | None = None,
        is_active: bool | None = None,
        is_public: bool | None = None,
    ) -> list[ProviderConfig]:
        query = select(ProviderConfig).options(
            joinedload(ProviderConfig.provider_spec),
            selectinload(ProviderConfig.model_instances)
        )

        conditions = []
        if provider_spec_id is not None:
            conditions.append(ProviderConfig.provider_spec_id == provider_spec_id)
        if user_id is not None:
            conditions.append(ProviderConfig.user_id == user_id)
        if is_active is not None:
            conditions.append(ProviderConfig.is_active == is_active)
        if is_public is not None:
            conditions.append(ProviderConfig.is_public == is_public)

        if conditions:
            query = query.where(and_(*conditions))

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create(self, entity: ProviderConfig) -> ProviderConfig:
        self.session.add(entity)
        await self.session.flush()
        # Reload with relationships
        result = await self.get(UUID(str(entity.id)))
        return result if result else entity

    async def update(self, entity: ProviderConfig) -> ProviderConfig:
        await self.session.merge(entity)
        await self.session.flush()
        return entity

    async def delete(self, id: UUID) -> bool:
        result = await self.session.execute(select(ProviderConfig).where(ProviderConfig.id == id))
        config = result.scalar_one_or_none()
        if config:
            await self.session.delete(config)
            await self.session.flush()
            return True
        return False 