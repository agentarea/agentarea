from uuid import UUID

from agentarea_common.base.repository import BaseRepository
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from agentarea_llm.domain.models import ModelSpec


class ModelSpecRepository(BaseRepository[ModelSpec]):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, id: UUID) -> ModelSpec | None:
        result = await self.session.execute(
            select(ModelSpec)
            .options(
                joinedload(ModelSpec.provider_spec),
                joinedload(ModelSpec.model_instances)
            )
            .where(ModelSpec.id == id)
        )
        return result.scalar_one_or_none()

    async def get_by_provider_and_model(self, provider_spec_id: UUID, model_name: str) -> ModelSpec | None:
        """Get model spec by provider and model name"""
        result = await self.session.execute(
            select(ModelSpec)
            .options(
                joinedload(ModelSpec.provider_spec),
                joinedload(ModelSpec.model_instances)
            )
            .where(
                and_(
                    ModelSpec.provider_spec_id == provider_spec_id,
                    ModelSpec.model_name == model_name
                )
            )
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        provider_spec_id: UUID | None = None,
        is_active: bool | None = None,
    ) -> list[ModelSpec]:
        query = select(ModelSpec).options(
            joinedload(ModelSpec.provider_spec),
            joinedload(ModelSpec.model_instances)
        )

        conditions = []
        if provider_spec_id is not None:
            conditions.append(ModelSpec.provider_spec_id == provider_spec_id)
        if is_active is not None:
            conditions.append(ModelSpec.is_active == is_active)

        if conditions:
            query = query.where(and_(*conditions))

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create(self, entity: ModelSpec) -> ModelSpec:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update(self, entity: ModelSpec) -> ModelSpec:
        await self.session.merge(entity)
        await self.session.flush()
        return entity

    async def delete(self, id: UUID) -> bool:
        result = await self.session.execute(select(ModelSpec).where(ModelSpec.id == id))
        model_spec = result.scalar_one_or_none()
        if model_spec:
            await self.session.delete(model_spec)
            await self.session.flush()
            return True
        return False

    async def upsert_by_provider_and_model(self, entity: ModelSpec) -> ModelSpec:
        """Upsert model spec by provider and model name - used in bootstrap"""
        existing = await self.get_by_provider_and_model(entity.provider_spec_id, entity.model_name)
        if existing:
            # Update existing
            existing.display_name = entity.display_name
            existing.description = entity.description
            existing.context_window = entity.context_window
            existing.is_active = entity.is_active
            return await self.update(existing)
        else:
            # Create new
            return await self.create(entity) 