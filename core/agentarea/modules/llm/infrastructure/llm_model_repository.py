from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentarea.common.base.repository import BaseRepository
from agentarea.modules.llm.domain.models import LLMModel, LLMProvider


class LLMModelRepository(BaseRepository[LLMModel]):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, id: UUID) -> LLMModel | None:
        result = await self.session.execute(
            select(LLMModel).options(selectinload(LLMModel.provider)).where(LLMModel.id == id)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        status: str | None = None,
        is_public: bool | None = None,
        provider: str | None = None,
    ) -> list[LLMModel]:
        query = select(LLMModel).options(selectinload(LLMModel.provider))

        conditions = []
        if status is not None:
            conditions.append(LLMModel.status == status)
        if is_public is not None:
            conditions.append(LLMModel.is_public == is_public)
        if provider is not None:
            query = query.join(LLMProvider)
            conditions.append(LLMProvider.name == provider)

        if conditions:
            query = query.where(and_(*conditions))

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create(self, entity: LLMModel) -> LLMModel:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update(self, entity: LLMModel) -> LLMModel:
        await self.session.merge(entity)
        await self.session.flush()
        return entity

    async def delete(self, id: UUID) -> bool:
        result = await self.session.execute(select(LLMModel).where(LLMModel.id == id))
        model = result.scalar_one_or_none()
        if model:
            await self.session.delete(model)
            await self.session.flush()
            return True
        return False
