from uuid import UUID

from agentarea_common.base.repository import BaseRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentarea_llm.domain.models import ProviderSpec


class ProviderSpecRepository(BaseRepository[ProviderSpec]):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, id: UUID) -> ProviderSpec | None:
        result = await self.session.execute(
            select(ProviderSpec)
            .options(
                selectinload(ProviderSpec.model_specs),
                selectinload(ProviderSpec.provider_configs)
            )
            .where(ProviderSpec.id == id)
        )
        return result.scalar_one_or_none()

    async def get_by_provider_key(self, provider_key: str) -> ProviderSpec | None:
        """Get provider spec by provider_key (e.g., 'openai', 'anthropic')"""
        result = await self.session.execute(
            select(ProviderSpec)
            .options(
                selectinload(ProviderSpec.model_specs),
                selectinload(ProviderSpec.provider_configs)
            )
            .where(ProviderSpec.provider_key == provider_key)
        )
        return result.scalar_one_or_none()

    async def list(self, is_builtin: bool | None = None, is_active: bool = True) -> list[ProviderSpec]:
        query = select(ProviderSpec).options(
            selectinload(ProviderSpec.model_specs),
            selectinload(ProviderSpec.provider_configs)
        )

        if is_builtin is not None:
            query = query.where(ProviderSpec.is_builtin == is_builtin)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create(self, entity: ProviderSpec) -> ProviderSpec:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update(self, entity: ProviderSpec) -> ProviderSpec:
        await self.session.merge(entity)
        await self.session.flush()
        return entity

    async def delete(self, id: UUID) -> bool:
        result = await self.session.execute(select(ProviderSpec).where(ProviderSpec.id == id))
        provider_spec = result.scalar_one_or_none()
        if provider_spec:
            await self.session.delete(provider_spec)
            await self.session.flush()
            return True
        return False

    async def upsert_by_provider_key(self, entity: ProviderSpec) -> ProviderSpec:
        """Upsert provider spec by provider_key - used in bootstrap"""
        existing = await self.get_by_provider_key(entity.provider_key)
        if existing:
            # Update existing
            existing.name = entity.name
            existing.description = entity.description
            existing.provider_type = entity.provider_type
            existing.icon = entity.icon
            existing.is_builtin = entity.is_builtin
            return await self.update(existing)
        else:
            # Create new
            return await self.create(entity) 