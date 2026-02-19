from uuid import UUID

from agentarea_common.base import RepositoryFactory
from agentarea_common.base.service import BaseCrudService
from agentarea_common.events.broker import EventBroker

from agentarea_agents.domain.events import AgentCreated, AgentDeleted, AgentUpdated
from agentarea_agents.domain.models import Agent
from agentarea_agents.infrastructure.repository import AgentRepository


class AgentService(BaseCrudService[Agent]):
    def __init__(self, repository_factory: RepositoryFactory, event_broker: EventBroker):
        # Create repository using factory
        repository = repository_factory.create_repository(AgentRepository)
        super().__init__(repository)
        self.repository_factory = repository_factory
        self.event_broker = event_broker

    def _get_agent_repository(self) -> AgentRepository:
        """Get the agent repository with proper type."""
        return self.repository_factory.create_repository(AgentRepository)

    async def create_agent(
        self,
        name: str,
        description: str,
        instruction: str,
        model_id: str,
        tools: dict | list | None = None,
        events_config: dict | None = None,
        planning: bool | None = None,
        skill_ids: list[UUID | str] | None = None,
    ) -> Agent:
        agent = Agent(
            name=name,
            description=description,
            instruction=instruction,
            model_id=model_id,
            tools=tools,
            events_config=events_config,
            planning=planning,
        )
        agent = await self.create(agent)

        # Set skill associations if provided
        if skill_ids:
            repo = self._get_agent_repository()
            await repo.set_skills(agent.id, [UUID(str(sid)) for sid in skill_ids])

        await self.event_broker.publish(
            AgentCreated(
                agent_id=agent.id,
                name=agent.name,
                description=agent.description,
                model_id=agent.model_id,
                tools=agent.tools,
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
        tools: dict | list | None = None,
        events_config: dict | None = None,
        planning: str | None = None,
        skill_ids: list[UUID | str] | None = None,
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
        if tools is not None:
            agent.tools = tools
        if events_config is not None:
            agent.events_config = events_config
        if planning is not None:
            agent.planning = planning

        agent = await self.update(agent)

        # Update skill associations if provided
        if skill_ids is not None:
            repo = self._get_agent_repository()
            await repo.set_skills(agent.id, [UUID(str(sid)) for sid in skill_ids])

        await self.event_broker.publish(
            AgentUpdated(
                agent_id=agent.id,
                name=agent.name,
                description=agent.description,
                model_id=agent.model_id,
                tools=agent.tools,
                events_config=agent.events_config,
                planning=agent.planning,
            )
        )

        return agent

    async def get_with_skills(self, id: UUID) -> Agent | None:
        """Get an agent with its skills loaded."""
        repo = self._get_agent_repository()
        return await repo.get_with_skills(id)

    async def delete_agent(self, id: UUID) -> bool:
        success = await self.delete(id)
        if success:
            await self.event_broker.publish(AgentDeleted(agent_id=id))
        return success
