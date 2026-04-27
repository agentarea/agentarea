"""MCPServersToolset — manage MCP server instances."""

import json

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method

from .base import platform_context


class MCPServersToolset(Toolset):
    """Manage MCP server instances: create, list, get, verify."""

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
        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            event_broker,
            _secret_mgr,
        ):
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
        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            event_broker,
            secret_mgr,
        ):
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
                    "verification": instance.verification,
                    "description": instance.description,
                },
                default=str,
            )

    @tool_method
    async def list(self) -> str:
        """List all MCP server instances in the workspace."""
        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            event_broker,
            secret_mgr,
        ):
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
                        "verification": i.verification,
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

        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            event_broker,
            secret_mgr,
        ):
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
                    "verification": instance.verification,
                    "last_dispatch": instance.last_dispatch,
                    "tools": instance.tools,
                    "description": instance.description,
                },
                default=str,
            )

    @tool_method
    async def list_specs(
        self,
        is_public: bool = False,
        tag: str = "",
        search: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> str:
        """List MCP server specs (templates) available in the workspace."""
        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            event_broker,
            _secret_mgr,
        ):
            from agentarea_mcp.application.service import MCPServerService

            service = MCPServerService(
                repository_factory=repo_factory,
                event_broker=event_broker,
            )
            servers, total = await service.list_servers(
                is_public=is_public if is_public else None,
                tag=tag or None,
                search=search or None,
                limit=limit,
                offset=offset,
            )
            return json.dumps(
                {
                    "items": [
                        {
                            "id": str(s.id),
                            "name": s.name,
                            "description": s.description,
                            "version": s.version,
                            "tags": s.tags,
                            "is_public": s.is_public,
                            "remote_url": s.remote_url,
                            "docker_image_url": s.docker_image_url,
                            "status": s.status,
                        }
                        for s in servers
                    ],
                    "total": total,
                },
                default=str,
            )

    @tool_method
    async def get_spec(self, spec_id: str) -> str:
        """Get an MCP server spec (template) by ID."""
        from uuid import UUID

        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            event_broker,
            _secret_mgr,
        ):
            from agentarea_mcp.application.service import MCPServerService

            service = MCPServerService(
                repository_factory=repo_factory,
                event_broker=event_broker,
            )
            server = await service.get(UUID(spec_id))
            if not server:
                return json.dumps({"error": "MCP server spec not found"})
            return json.dumps(
                {
                    "id": str(server.id),
                    "name": server.name,
                    "description": server.description,
                    "version": server.version,
                    "tags": server.tags,
                    "env_schema": server.env_schema,
                    "remote_url": server.remote_url,
                    "docker_image_url": server.docker_image_url,
                    "status": server.status,
                    "registry_url": server.registry_url,
                },
                default=str,
            )

    @tool_method
    async def delete_spec(self, spec_id: str) -> str:
        """Delete an MCP server spec (template) by ID."""
        from uuid import UUID

        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            event_broker,
            _secret_mgr,
        ):
            from agentarea_mcp.application.service import MCPServerService

            service = MCPServerService(
                repository_factory=repo_factory,
                event_broker=event_broker,
            )
            deleted = await service.delete_mcp_server(UUID(spec_id))
            return json.dumps({"deleted": deleted})

    @tool_method
    async def delete_instance(self, instance_id: str) -> str:
        """Delete an MCP server instance."""
        from uuid import UUID

        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            event_broker,
            secret_mgr,
        ):
            from agentarea_mcp.application.service import MCPServerInstanceService

            service = MCPServerInstanceService(
                repository_factory=repo_factory,
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
            deleted = await service.delete_instance(UUID(instance_id))
            return json.dumps({"deleted": deleted})

    @tool_method
    async def verify(self, instance_id: str) -> str:
        """Run end-to-end verification on an MCP server instance.

        Provisions (if needed), waits for readiness, and lists tools.
        Returns the fresh verification payload.
        """
        from uuid import UUID

        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            event_broker,
            secret_mgr,
        ):
            from agentarea_mcp.application.service import MCPServerInstanceService

            service = MCPServerInstanceService(
                repository_factory=repo_factory,
                event_broker=event_broker,
                secret_manager=secret_mgr,
            )
            result = await service.verify_instance(UUID(instance_id))
            return json.dumps(result, default=str)
