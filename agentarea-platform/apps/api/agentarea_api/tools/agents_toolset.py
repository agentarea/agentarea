"""AgentsToolset — manage agents in the workspace."""

import json

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method

from .base import platform_context


class AgentsToolset(Toolset):
    """Manage agents: list, get, create, update, delete."""

    @tool_method
    async def list(self, limit: int = 50, offset: int = 0) -> str:
        """List all agents in the workspace."""
        async with platform_context() as (_session, _user_ctx, repo_factory, event_broker, _):
            from agentarea_agents.application.agent_service import AgentService
            from agentarea_common.auth.authorization import AuthorizationService
            from agentarea_common.di.container import resolve

            authz = resolve(AuthorizationService)
            service = AgentService(repo_factory, event_broker, authorization_service=authz)
            agents = await service.list()
            return json.dumps(
                [{"id": str(a.id), "name": a.name, "description": a.description} for a in agents],
                default=str,
            )

    @tool_method
    async def get(self, agent_id: str) -> str:
        """Get agent details by ID."""
        from uuid import UUID

        async with platform_context() as (_session, _user_ctx, repo_factory, event_broker, _):
            from agentarea_agents.application.agent_service import AgentService
            from agentarea_common.auth.authorization import AuthorizationService
            from agentarea_common.di.container import resolve

            authz = resolve(AuthorizationService)
            service = AgentService(repo_factory, event_broker, authorization_service=authz)
            agent = await service.get(UUID(agent_id))
            if not agent:
                return json.dumps({"error": "Agent not found"})
            return json.dumps(
                {
                    "id": str(agent.id),
                    "name": agent.name,
                    "description": agent.description,
                    "model_id": agent.model_id,
                    "instruction": agent.instruction,
                    "agent_type": agent.agent_type,
                },
                default=str,
            )

    @tool_method
    async def create(
        self,
        name: str,
        description: str = "",
        instruction: str = "",
        model_id: str = "",
        agent_type: str = "stateless",
    ) -> str:
        """Create a new agent."""
        async with platform_context() as (_session, _user_ctx, repo_factory, event_broker, _):
            from agentarea_agents.application.agent_service import AgentService
            from agentarea_common.auth.authorization import AuthorizationService
            from agentarea_common.di.container import resolve

            authz = resolve(AuthorizationService)
            service = AgentService(repo_factory, event_broker, authorization_service=authz)
            agent = await service.create_agent(
                name=name,
                description=description,
                instruction=instruction,
                model_id=model_id,
                agent_type=agent_type,
            )
            return json.dumps({"id": str(agent.id), "name": agent.name}, default=str)

    @tool_method
    async def update(
        self,
        agent_id: str,
        name: str = "",
        description: str = "",
        instruction: str = "",
        model_id: str = "",
    ) -> str:
        """Update an existing agent."""
        from uuid import UUID

        async with platform_context() as (_session, _user_ctx, repo_factory, event_broker, _):
            from agentarea_agents.application.agent_service import AgentService
            from agentarea_common.auth.authorization import AuthorizationService
            from agentarea_common.di.container import resolve

            authz = resolve(AuthorizationService)
            service = AgentService(repo_factory, event_broker, authorization_service=authz)
            kwargs = {}
            if name:
                kwargs["name"] = name
            if description:
                kwargs["description"] = description
            if instruction:
                kwargs["instruction"] = instruction
            if model_id:
                kwargs["model_id"] = model_id
            agent = await service.update_agent(UUID(agent_id), **kwargs)
            if not agent:
                return json.dumps({"error": "Agent not found"})
            return json.dumps({"id": str(agent.id), "name": agent.name}, default=str)

    @tool_method
    async def delete(self, agent_id: str) -> str:
        """Delete an agent by ID."""
        from uuid import UUID

        async with platform_context() as (_session, _user_ctx, repo_factory, event_broker, _):
            from agentarea_agents.application.agent_service import AgentService
            from agentarea_common.auth.authorization import AuthorizationService
            from agentarea_common.di.container import resolve

            authz = resolve(AuthorizationService)
            service = AgentService(repo_factory, event_broker, authorization_service=authz)
            deleted = await service.delete_agent(UUID(agent_id))
            return json.dumps({"deleted": deleted})
