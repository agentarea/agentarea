from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea.common.base.repository import BaseRepository
from agentarea.modules.llm.domain.models import LLMModelInstance


class LLMModelInstanceRepository(BaseRepository[LLMModelInstance]):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, id: UUID) -> LLMModelInstance | None:
        async with self.session.begin():
            result = await self.session.execute(
                select(LLMModelInstance).where(LLMModelInstance.id == id)
            )
            return result.scalar_one_or_none()

    async def list(
        self,
        model_id: UUID | None = None,
        status: str | None = None,
        is_public: bool | None = None
    ) -> list[LLMModelInstance]:
        async with self.session.begin():
            query = select(LLMModelInstance)

            conditions = []
            if model_id is not None:
                conditions.append(LLMModelInstance.model_id == model_id)
            if status is not None:
                conditions.append(LLMModelInstance.status == status)
            if is_public is not None:
                conditions.append(LLMModelInstance.is_public == is_public)

            if conditions:
                query = query.where(and_(*conditions))

            result = await self.session.execute(query)
            return list(result.scalars().all())

    async def create(self, instance: LLMModelInstance) -> LLMModelInstance:
        async with self.session.begin():
            self.session.add(instance)
            await self.session.flush()
            return instance

    async def update(self, instance: LLMModelInstance) -> LLMModelInstance:
        async with self.session.begin():
            await self.session.merge(instance)
            await self.session.flush()
            return instance

    async def delete(self, id: UUID) -> bool:
        async with self.session.begin():
            result = await self.session.execute(
                select(LLMModelInstance).where(LLMModelInstance.id == id)
            )
            instance = result.scalar_one_or_none()
            if instance:
                await self.session.delete(instance)
                await self.session.flush()
                return True
            return False
