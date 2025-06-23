from uuid import UUID

from agentarea_common.base.repository import BaseRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_agents.domain.models import Agent


class AgentRepository(BaseRepository[Agent]):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, id: UUID) -> Agent | None:
        result = await self.session.execute(select(Agent).where(Agent.id == id))
        return result.scalar_one_or_none()

    async def list(self) -> list[Agent]:
        result = await self.session.execute(select(Agent))
        return list(result.scalars().all())

    async def create(self, agent: Agent) -> Agent:
        self.session.add(agent)
        await self.session.flush()
        return agent

    async def update(self, agent: Agent) -> Agent:
        await self.session.merge(agent)
        await self.session.flush()
        return agent

    async def delete(self, id: UUID) -> bool:
        result = await self.session.execute(select(Agent).where(Agent.id == id))
        agent = result.scalar_one_or_none()
        if agent:
            await self.session.delete(agent)
            await self.session.flush()
            return True
        return False
