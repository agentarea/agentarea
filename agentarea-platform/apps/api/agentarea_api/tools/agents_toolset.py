"""AgentsToolset — manage agents in the workspace.

Tool method signatures are explicit kwargs (MCP-idiomatic flat wire schema)
but the source of truth is the Pydantic DTO ``AgentCreate``/``AgentUpdate``
in ``agentarea_agents.schemas.dto``. The contract test in
``tests/contracts/test_mcp_rest_parity.py`` enforces parity.
"""

import builtins
import json
from typing import Any
from uuid import UUID

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.schemas.dto import AgentCreate, AgentTypeLiteral, AgentUpdate
from agentarea_agents.schemas.import_export import ToolConfig
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import enforced_in_handler, requires, unrestricted
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.resource_visibility import readable_resource_ids
from agentarea_common.di.container import resolve
from pydantic import TypeAdapter

from .base import platform_context, platform_read_context

_TOOL_LIST = TypeAdapter(list[ToolConfig])


def _build_service(repo_factory, event_broker) -> AgentService:
    authz = resolve(AuthorizationService)
    return AgentService(repo_factory, event_broker, authorization_service=authz)


@toolset(
    namespace="agentarea/agents",
    display_name="Agent Management",
    description="Create, list, update, and delete agents in the workspace.",
    category="platform",
    plane="build",
)
class AgentsToolset(Toolset):
    """Manage agents: list, get, create, update, delete."""

    @tool_method(effect="read")
    @enforced_in_handler("rows the graph says this caller may read; see readable_resource_ids")
    async def list(self, limit: int = 50, offset: int = 0) -> str:
        """List all agents in the workspace."""
        async with platform_read_context() as (_s, user_ctx, repo_factory, event_broker, _):
            service = _build_service(repo_factory, event_broker)
            agents = await service.list()
            readable = await readable_resource_ids(user_ctx.user_id)
            return json.dumps(
                [
                    {"id": str(a.id), "name": a.name, "description": a.description}
                    for a in agents
                    if str(a.id) in readable
                ],
                default=str,
            )

    @tool_method(effect="read")
    @requires("read", "agent", id_param="agent_id")
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

    @tool_method(effect="write")
    @unrestricted("any member may create an agent, as POST /v1/agents allows")
    async def create(
        self,
        name: str,
        model_id: str,
        tools: builtins.list[dict[str, Any]],
        description: str = "",
        instruction: str = "",
        agent_type: AgentTypeLiteral = "stateless",
    ) -> str:
        """Create a new agent.

        ``tools`` is required: pass [] for an agent with no tools. Built-in
        toolsets are ``{"type": "code", "name": "agentarea/shell"}``; GET
        /v1/agents/tools lists them.
        """
        payload = AgentCreate(
            name=name,
            description=description,
            instruction=instruction,
            model_id=model_id,
            tools=_TOOL_LIST.validate_python(tools),
            agent_type=agent_type,
        )
        async with platform_context() as (_s, _u, repo_factory, event_broker, _):
            service = _build_service(repo_factory, event_broker)
            agent = await service.create_agent(payload)
            return json.dumps({"id": str(agent.id), "name": agent.name}, default=str)

    @tool_method(effect="write")
    @requires("edit", "agent", id_param="agent_id")
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

    @tool_method(effect="destructive")
    @requires("delete", "agent", id_param="agent_id")
    async def delete(self, agent_id: str) -> str:
        """Delete an agent by ID."""
        async with platform_context() as (_s, _u, repo_factory, event_broker, _):
            service = _build_service(repo_factory, event_broker)
            deleted = await service.delete_agent(UUID(agent_id))
            return json.dumps({"deleted": deleted})
