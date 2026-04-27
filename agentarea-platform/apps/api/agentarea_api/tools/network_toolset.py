"""NetworkToolset — workspace topology overview."""

import json

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method

from .base import platform_read_context


class NetworkToolset(Toolset):
    """Inspect the workspace network topology (agents, skills, MCP instances, triggers)."""

    @tool_method
    async def get_topology(self) -> str:
        """Return all nodes and edges in the workspace's agent/skill/MCP/trigger graph."""
        async with platform_read_context() as (_session, user_ctx, _repo, _broker, _secret):
            from agentarea_api.api.v1.network import get_network_topology

            response = await get_network_topology(user_context=user_ctx)
            return response.model_dump_json()
