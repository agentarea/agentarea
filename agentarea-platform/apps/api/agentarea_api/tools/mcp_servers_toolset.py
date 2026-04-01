"""MCPServersToolset — manage MCP server instances."""

import json

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method

from .base import platform_context


class MCPServersToolset(Toolset):
    """Manage MCP server instances: create, list, get, start, stop."""

    @property
    def name(self) -> str:
        return "mcp_servers"

    @tool_method
    async def create_spec(
        self,
        name: str,
        description: str,
        remote_url: str = "",
        docker_image_url: str = "",
        version: str = "1.0.0",
    ) -> str:
        """Create a new MCP server spec (template).

        For remote HTTP servers: provide remote_url.
        For docker-based servers: provide docker_image_url.
        """
        async with platform_context() as (_session, _user_ctx, repo_factory, event_broker, _secret_mgr):
            from agentarea_mcp.application.service import MCPServerService

            service = MCPServerService(
                repository_factory=repo_factory,
                event_broker=event_broker,
            )
            server = await service.create_mcp_server(
                name=name,
                description=description,
                docker_image_url=docker_image_url or None,
                remote_url=remote_url or None,
                version=version,
            )
            return json.dumps(
                {
                    "id": str(server.id),
                    "name": server.name,
                    "remote_url": server.remote_url,
                    "docker_image_url": server.docker_image_url,
                    "status": server.status,
                },
                default=str,
            )

    @tool_method
    async def create(
        self,
        name: str,
        json_spec: str,
        description: str = "",
        server_spec_id: str = "",
        auth_config_id: str = "",
    ) -> str:
        """Create a new MCP server instance.

        Args:
            name: Display name for the server
            json_spec: JSON string with server config (e.g. {"url": "https://...", "type": "http"})
            description: Optional description
            server_spec_id: Optional ID of an MCP server spec template
            auth_config_id: Optional ID of an auth config for OAuth servers
        """
        async with platform_context() as (_session, _user_ctx, repo_factory, event_broker, secret_mgr):
            from agentarea_mcp.application.service import MCPServerInstanceService

            service = MCPServerInstanceService(
                repository_factory=repo_factory,
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
            spec = json.loads(json_spec) if isinstance(json_spec, str) else json_spec
            instance = await service.create_instance(
                name=name,
                description=description or None,
                server_spec_id=server_spec_id or None,
                json_spec=spec,
                auth_config_id=auth_config_id or None,
            )
            if not instance:
                return json.dumps({"error": "Failed to create MCP server instance"})
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
    async def list(self) -> str:
        """List all MCP server instances in the workspace."""
        async with platform_context() as (_session, _user_ctx, repo_factory, event_broker, secret_mgr):
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

        async with platform_context() as (_session, _user_ctx, repo_factory, event_broker, secret_mgr):
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

        async with platform_context() as (_session, _user_ctx, repo_factory, event_broker, secret_mgr):
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

        async with platform_context() as (_session, _user_ctx, repo_factory, event_broker, secret_mgr):
            from agentarea_mcp.application.service import MCPServerInstanceService

            service = MCPServerInstanceService(
                repository_factory=repo_factory,
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
            stopped = await service.stop_instance(UUID(instance_id))
            return json.dumps({"stopped": stopped})
