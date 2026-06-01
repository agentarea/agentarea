import logging
from typing import Any, cast
from uuid import UUID

from agentarea_common.audit import audited
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.base import RepositoryFactory
from agentarea_common.base.service import BaseCrudService
from agentarea_common.events.broker import EventBroker
from agentarea_common.utils.slug import generate_slug

from agentarea_agents.domain.events import AgentCreated, AgentDeleted, AgentUpdated
from agentarea_agents.domain.models import Agent
from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_agents.schemas.dto import AgentCreate, AgentUpdate

logger = logging.getLogger(__name__)


class AgentService(BaseCrudService[Agent]):
    def __init__(
        self,
        repository_factory: RepositoryFactory,
        event_broker: EventBroker,
        authorization_service: AuthorizationService,
    ):
        repository = repository_factory.create_repository(AgentRepository)
        super().__init__(repository)
        self.repository_factory = repository_factory
        self.event_broker = event_broker
        self._user_context = repository_factory.user_context
        self._authz = authorization_service

    async def _check_write_access(self, agent: Agent) -> None:
        """Check if the current user can mutate this agent.

        Raises:
            PermissionError: If the user cannot write to the agent's workspace.
        """
        if not await self._authz.can_write_workspace(self._user_context, agent.workspace_id):
            raise PermissionError(f"Cannot modify agent in workspace '{agent.workspace_id}'")

    def _get_agent_repository(self) -> AgentRepository:
        """Get the agent repository with proper type."""
        return self.repository_factory.create_repository(AgentRepository)

    async def _resolve_unique_slug(self, name: str) -> str:
        """Generate a workspace-unique slug from ``name``.

        Tries ``base``, then ``base-2``, ``base-3``, ... up to ``base-999``.
        """
        repo = self._get_agent_repository()
        base = generate_slug(name)

        if await repo.get_by_slug(base) is None:
            return base

        for suffix in range(2, 1000):
            candidate = f"{base}-{suffix}"
            if await repo.get_by_slug(candidate) is None:
                return candidate

        raise ValueError(f"Exhausted collision suffixes (-2..-999) for slug base '{base}'")

    @audited("agent.create", resource_type="agent")
    async def create_agent(self, payload: AgentCreate) -> Agent:
        tools = [t.model_dump(exclude_none=True) for t in payload.tools] if payload.tools else None
        events_config = payload.events_config.model_dump() if payload.events_config else None

        slug = await self._resolve_unique_slug(payload.name)

        agent = Agent(
            name=payload.name,
            slug=slug,
            description=payload.description,
            instruction=payload.instruction,
            model_id=payload.model_id,
            tools=tools,
            events_config=events_config,
            planning=payload.planning,
            a2ui_enabled=payload.a2ui_enabled,
            agent_type=payload.agent_type,
        )
        agent = await self.create(agent)

        if payload.skill_ids:
            repo = self._get_agent_repository()
            await repo.set_skills(agent.id, [UUID(str(sid)) for sid in payload.skill_ids])

        await self.event_broker.publish(
            AgentCreated(
                agent_id=agent.id,
                name=agent.name,
                description=agent.description or "",
                model_id=agent.model_id or "",
                tools=agent.tools,
                events_config=agent.events_config,
                planning=agent.planning,
                a2ui_enabled=agent.a2ui_enabled,
            )
        )

        return agent

    @audited("agent.update", resource_type="agent", resource_id_param="id")
    async def update_agent(self, id: UUID, payload: AgentUpdate) -> Agent | None:
        agent = await self.get(id)
        if not agent:
            return None

        await self._check_write_access(agent)

        patch = payload.model_dump(exclude_unset=True)

        if "name" in patch:
            agent.name = patch["name"]
        if "capabilities" in patch:
            cast(Any, agent).capabilities = patch["capabilities"]
        if "description" in patch:
            agent.description = patch["description"]
        if "instruction" in patch:
            agent.instruction = patch["instruction"]
        if "model_id" in patch:
            agent.model_id = patch["model_id"]
        if "tools" in patch and payload.tools is not None:
            agent.tools = [t.model_dump(exclude_none=True) for t in payload.tools]
        if "events_config" in patch and payload.events_config is not None:
            agent.events_config = payload.events_config.model_dump()
        if "planning" in patch:
            agent.planning = patch["planning"]
        if "a2ui_enabled" in patch:
            agent.a2ui_enabled = patch["a2ui_enabled"]
        if "agent_type" in patch:
            agent.agent_type = patch["agent_type"]

        agent = await self.update(agent)

        if "skill_ids" in patch and payload.skill_ids is not None:
            repo = self._get_agent_repository()
            await repo.set_skills(agent.id, [UUID(str(sid)) for sid in payload.skill_ids])

        await self.event_broker.publish(
            AgentUpdated(
                agent_id=agent.id,
                name=agent.name,
                description=agent.description,
                model_id=agent.model_id,
                tools=agent.tools,
                events_config=agent.events_config,
                planning=agent.planning,
                a2ui_enabled=agent.a2ui_enabled,
            )
        )

        return agent

    async def get_by_name(self, name: str) -> Agent | None:
        """Get an agent by name."""
        repo = self._get_agent_repository()
        return await repo.get_agent_by_name(name)

    async def get_by_slug(self, slug: str) -> Agent | None:
        """Get an agent by workspace-scoped slug."""
        repo = self._get_agent_repository()
        return await repo.get_by_slug(slug)

    async def get_with_skills(self, id: UUID) -> Agent | None:
        """Get an agent with its skills loaded."""
        repo = self._get_agent_repository()
        return await repo.get_with_skills(id)

    @audited("agent.delete", resource_type="agent", resource_id_param="id")
    async def delete_agent(self, id: UUID) -> bool:
        agent = await self.get(id)
        if not agent:
            return False
        await self._check_write_access(agent)
        success = await self.delete(id)
        if success:
            await self.event_broker.publish(AgentDeleted(agent_id=id))
        return success
