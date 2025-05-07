from uuid import UUID

from agentarea.common.base.service import BaseCrudService
from agentarea.common.events.broker import EventBroker

from ..domain.events import AgentCreated, AgentDeleted, AgentUpdated
from ..domain.models import Agent
from ..infrastructure.repository import AgentRepository


class AgentService(BaseCrudService[Agent]):
    def __init__(self, repository: AgentRepository, event_broker: EventBroker):
        super().__init__(repository)
        self.event_broker = event_broker

    async def create_agent(
        self,
        name: str,
        capabilities: list[str],
        description: str,
        model_id: str,
        tools_config: dict = None,
        events_config: dict = None,
        planning: str = None,
    ) -> Agent:
        agent = Agent(
            name=name,
            capabilities=capabilities,
            description=description,
            model_id=model_id,
            tools_config=tools_config,
            events_config=events_config,
            planning=planning,
        )
        agent = await self.create(agent)

        await self.event_broker.publish(
            AgentCreated(
                agent_id=agent.id,
                name=agent.name,
                capabilities=agent.capabilities,
                description=agent.description,
                model_id=agent.model_id,
                tools_config=agent.tools_config,
                events_config=agent.events_config,
                planning=agent.planning,
            )
        )

        return agent

    async def update_agent(
        self,
        id: UUID,
        name: str | None = None,
        capabilities: list[str] | None = None,
        description: str | None = None,
        model_id: str | None = None,
        tools_config: dict | None = None,
        events_config: dict | None = None,
        planning: str | None = None,
    ) -> Agent | None:
        agent = await self.get(id)
        if not agent:
            return None

        if name is not None:
            agent.name = name
        if capabilities is not None:
            agent.capabilities = capabilities
        if description is not None:
            agent.description = description
        if model_id is not None:
            agent.model_id = model_id
        if tools_config is not None:
            agent.tools_config = tools_config
        if events_config is not None:
            agent.events_config = events_config
        if planning is not None:
            agent.planning = planning

        agent = await self.update(agent)

        await self.event_broker.publish(
            AgentUpdated(
                agent_id=agent.id,
                name=agent.name,
                capabilities=agent.capabilities,
                description=agent.description,
                model_id=agent.model_id,
                tools_config=agent.tools_config,
                events_config=agent.events_config,
                planning=agent.planning,
            )
        )

        return agent

    async def delete_agent(self, id: UUID) -> bool:
        success = await self.delete(id)
        if success:
            await self.event_broker.publish(AgentDeleted(agent_id=id))
        return success
