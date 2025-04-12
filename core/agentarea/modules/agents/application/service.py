from typing import List, Optional
from uuid import UUID

from agentarea.common.base.service import BaseService
from agentarea.common.events.broker import EventBroker

from ..domain.events import AgentCreated, AgentDeleted, AgentUpdated
from ..domain.models import Agent
from ..infrastructure.repository import AgentRepository


class AgentService(BaseService[Agent]):
    def __init__(self, repository: AgentRepository, event_broker: EventBroker):
        super().__init__(repository)
        self.event_broker = event_broker

    async def create_agent(self, name: str, capabilities: List[str]) -> Agent:
        agent = Agent(name=name, capabilities=capabilities)
        agent = await self.create(agent)

        await self.event_broker.publish(
            AgentCreated(
                agent_id=agent.id, name=agent.name, capabilities=agent.capabilities
            )
        )

        return agent

    async def update_agent(
        self,
        id: UUID,
        name: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
    ) -> Optional[Agent]:
        agent = await self.get(id)
        if not agent:
            return None

        if name is not None:
            agent.name = name
        if capabilities is not None:
            agent.capabilities = capabilities

        agent = await self.update(agent)

        await self.event_broker.publish(
            AgentUpdated(
                agent_id=agent.id, name=agent.name, capabilities=agent.capabilities
            )
        )

        return agent

    async def delete_agent(self, id: UUID) -> bool:
        success = await self.delete(id)
        if success:
            await self.event_broker.publish(AgentDeleted(agent_id=id))
        return success
