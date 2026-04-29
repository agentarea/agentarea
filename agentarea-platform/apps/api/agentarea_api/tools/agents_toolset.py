"""AgentsToolset — manage agents in the workspace.

Tool method signatures are explicit kwargs (MCP-idiomatic flat wire schema)
but the source of truth is the Pydantic DTO ``AgentCreate``/``AgentUpdate``
in ``agentarea_agents.schemas.dto``. The contract test in
``tests/contracts/test_mcp_rest_parity.py`` enforces parity.
"""

import json
from uuid import UUID

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.schemas.dto import AgentCreate, AgentTypeLiteral, AgentUpdate
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.di.container import resolve

from .base import platform_context, platform_read_context


def _build_service(repo_factory, event_broker) -> AgentService:
    authz = resolve(AuthorizationService)
    return AgentService(repo_factory, event_broker, authorization_service=authz)


@toolset(
    namespace="agentarea/agents",
    display_name="Agent Management",
    description="Create, list, update, and delete agents in the workspace.",
    category="platform",
)
class AgentsToolset(Toolset):
    """Manage agents: list, get, create, update, delete."""

    @tool_method
    async def list(self, limit: int = 50, offset: int = 0) -> str:
        """List all agents in the workspace."""
        async with platform_read_context() as (_s, _u, repo_factory, event_broker, _):
            service = _build_service(repo_factory, event_broker)
            agents = await service.list()
            return json.dumps(
                [{"id": str(a.id), "name": a.name, "description": a.description} for a in agents],
                default=str,
            )

    @tool_method
    async def get(self, agent_id: str) -> str:
        """Get agent details by ID."""
        async with platform_read_context() as (_s, _u, repo_factory, event_broker, _):
            service = _build_service(repo_factory, event_broker)
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
        model_id: str,
        description: str = "",
        instruction: str = "",
        agent_type: AgentTypeLiteral = "stateless",
    ) -> str:
        """Create a new agent."""
        payload = AgentCreate(
            name=name,
            description=description,
            instruction=instruction,
            model_id=model_id,
            agent_type=agent_type,
        )
        async with platform_context() as (_s, _u, repo_factory, event_broker, _):
            service = _build_service(repo_factory, event_broker)
            agent = await service.create_agent(payload)
            return json.dumps({"id": str(agent.id), "name": agent.name}, default=str)

    @tool_method
    async def update(
        self,
        agent_id: str,
        name: str | None = None,
        description: str | None = None,
        instruction: str | None = None,
        model_id: str | None = None,
    ) -> str:
        """Update an existing agent."""
        patch: dict[str, object] = {}
        if name is not None:
            patch["name"] = name
        if description is not None:
            patch["description"] = description
        if instruction is not None:
            patch["instruction"] = instruction
        if model_id is not None:
            patch["model_id"] = model_id
        payload = AgentUpdate.model_validate(patch)

        async with platform_context() as (_s, _u, repo_factory, event_broker, _):
            service = _build_service(repo_factory, event_broker)
            agent = await service.update_agent(UUID(agent_id), payload)
            if not agent:
                return json.dumps({"error": "Agent not found"})
            return json.dumps({"id": str(agent.id), "name": agent.name}, default=str)

    @tool_method
    async def delete(self, agent_id: str) -> str:
        """Delete an agent by ID."""
        async with platform_context() as (_s, _u, repo_factory, event_broker, _):
            service = _build_service(repo_factory, event_broker)
            deleted = await service.delete_agent(UUID(agent_id))
            return json.dumps({"deleted": deleted})
