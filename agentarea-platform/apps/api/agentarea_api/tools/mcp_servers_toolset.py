"""MCPServersToolset — manage MCP server instances."""

import json

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method

from .base import platform_context


class MCPServersToolset(Toolset):
    """Manage MCP server instances: list, get, start, stop."""

    @property
    def name(self) -> str:
        return "mcp_servers"

    @tool_method
    async def list(self) -> str:
        """List all MCP server instances in the workspace."""
        async with platform_context() as (session, user_ctx, repo_factory, event_broker, secret_mgr):
            from agentarea_mcp.application.service import MCPServerInstanceService

            service = MCPServerInstanceService(
                repository_factory=repo_factory,
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
            instances = await service.list()
            return json.dumps(
                [
                    {
                        "id": str(i.id),
                        "name": i.name,
                        "status": i.status,
                        "description": i.description,
                    }
                    for i in instances
                ],
                default=str,
            )

    @tool_method
    async def get(self, instance_id: str) -> str:
        """Get details of an MCP server instance."""
        from uuid import UUID

        async with platform_context() as (session, user_ctx, repo_factory, event_broker, secret_mgr):
            from agentarea_mcp.application.service import MCPServerInstanceService

            service = MCPServerInstanceService(
                repository_factory=repo_factory,
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
            instance = await service.get(UUID(instance_id))
            if not instance:
                return json.dumps({"error": "MCP server instance not found"})
            return json.dumps(
                {
                    "id": str(instance.id),
                    "name": instance.name,
                    "status": instance.status,
                    "description": instance.description,
                },
                default=str,
            )

    @tool_method
    async def start(self, instance_id: str) -> str:
        """Start an MCP server instance."""
        from uuid import UUID

        async with platform_context() as (session, user_ctx, repo_factory, event_broker, secret_mgr):
            from agentarea_mcp.application.service import MCPServerInstanceService

            service = MCPServerInstanceService(
                repository_factory=repo_factory,
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
            started = await service.start_instance(UUID(instance_id))
            return json.dumps({"started": started})

    @tool_method
    async def stop(self, instance_id: str) -> str:
        """Stop a running MCP server instance."""
        from uuid import UUID

        async with platform_context() as (session, user_ctx, repo_factory, event_broker, secret_mgr):
            from agentarea_mcp.application.service import MCPServerInstanceService

            service = MCPServerInstanceService(
                repository_factory=repo_factory,
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
            stopped = await service.stop_instance(UUID(instance_id))
            return json.dumps({"stopped": stopped})
