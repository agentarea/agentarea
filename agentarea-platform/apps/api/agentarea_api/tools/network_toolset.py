"""NetworkToolset — workspace topology overview."""

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset

from .base import platform_read_context


@toolset(
    namespace="agentarea/network",
    display_name="Network",
    description="Inspect workspace network topology (agents, skills, MCP instances, triggers).",
    category="platform",
    plane="observe",
)
class NetworkToolset(Toolset):
    """Inspect the workspace network topology (agents, skills, MCP instances, triggers)."""

    @tool_method(effect="read")
    async def get_topology(self) -> str:
        """Return all nodes and edges in the workspace's agent/skill/MCP/trigger graph."""
        async with platform_read_context() as (_session, user_ctx, _repo, _broker, _secret):
            from agentarea_api.api.v1.network import get_network_topology

            response = await get_network_topology(user_context=user_ctx)
            return response.model_dump_json()
