"""MCPServersToolset — manage MCP server specs and instances.

Tool method signatures are explicit kwargs (MCP-idiomatic flat wire schema)
but the source of truth is the Pydantic DTOs in
``agentarea_mcp.schemas.dto`` (``MCPServerCreate``,
``MCPServerInstanceCreate``, plus their ``Update`` siblings). The contract
test in ``tests/unit/test_mcp_rest_parity.py`` enforces parity between
toolset kwargs and DTO fields.
"""

import json
from typing import Any
from uuid import UUID

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_mcp.schemas.dto import (
    MCPServerCreate,
    MCPServerInstanceCreate,
    MCPServerInstanceUpdate,
    MCPServerUpdate,
)

from .base import platform_context, platform_read_context


def _serialize_server(server: Any) -> dict:
    return {
        "id": str(server.id),
        "name": server.name,
        "description": server.description,
        "version": server.version,
        "tags": server.tags,
        "is_public": server.is_public,
        "remote_url": server.remote_url,
        "docker_image_url": server.docker_image_url,
        "status": server.status,
    }


def _serialize_instance(instance: Any) -> dict:
    return {
        "id": str(instance.id),
        "name": instance.name,
        "description": instance.description,
        "verification": instance.verification,
        "server_spec_id": instance.server_spec_id,
    }


@toolset(
    namespace="agentarea/mcp_servers",
    display_name="MCP Server Management",
    description="Start, stop, and manage MCP server instances.",
    category="platform",
)
class MCPServersToolset(Toolset):
    """Manage MCP server specs (templates) and instances."""

    @property
    def name(self) -> str:
        return "mcp_servers"

    # ------------------------------------------------------------------
    # Specs (catalog templates)
    # ------------------------------------------------------------------

    @tool_method
    async def create_spec(
        self,
        name: str,
        description: str,
        docker_image_url: str | None = None,
        remote_url: str | None = None,
        version: str = "1.0.0",
        tags: list[str] | None = None,
        is_public: bool = False,
        env_schema_json: str = "",
        cmd_json: str = "",
        json_spec_json: str = "",
        registry_url: str | None = None,
    ) -> str:
        """Create a new MCP server spec (catalog template).

        Args:
            name: Human-readable spec name (unique per workspace).
            description: Short summary of what this MCP server provides.
            docker_image_url: Docker image URL for container-based servers.
            remote_url: Remote endpoint URL for HTTP-based servers.
            version: Semantic version string (default ``1.0.0``).
            tags: Tags used for search and categorization.
            is_public: If true, the spec is visible across workspaces.
            env_schema_json: JSON-encoded array of env-var schema entries
                (KeyValueInput; mark secrets with ``isSecret: true``).
            cmd_json: JSON-encoded array overriding the container CMD.
            json_spec_json: JSON-encoded raw ServerJSON spec from the registry.
            registry_url: Source registry URL the spec was imported from.
        """
        env_schema = json.loads(env_schema_json) if env_schema_json else None
        cmd = json.loads(cmd_json) if cmd_json else None
        json_spec = json.loads(json_spec_json) if json_spec_json else None

        payload = MCPServerCreate(
            name=name,
            description=description,
            docker_image_url=docker_image_url,
            remote_url=remote_url,
            version=version,
            tags=tags or [],
            is_public=is_public,
            env_schema=env_schema,
            cmd=cmd,
            json_spec=json_spec,
            registry_url=registry_url,
        )

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
            server = await service.create_mcp_server(payload)
            return json.dumps(_serialize_server(server), default=str)

    @tool_method
    async def update_spec(
        self,
        spec_id: str,
        name: str | None = None,
        description: str | None = None,
        docker_image_url: str | None = None,
        remote_url: str | None = None,
        version: str | None = None,
        tags: list[str] | None = None,
        is_public: bool | None = None,
        status: str | None = None,
        env_schema_json: str = "",
        cmd_json: str = "",
        json_spec_json: str = "",
        registry_url: str | None = None,
    ) -> str:
        """Update fields on an existing MCP server spec. Only fields explicitly
        set are written; pass ``None`` to leave a field untouched.
        """
        patch: dict[str, Any] = {}
        if name is not None:
            patch["name"] = name
        if description is not None:
            patch["description"] = description
        if docker_image_url is not None:
            patch["docker_image_url"] = docker_image_url
        if remote_url is not None:
            patch["remote_url"] = remote_url
        if version is not None:
            patch["version"] = version
        if tags is not None:
            patch["tags"] = tags
        if is_public is not None:
            patch["is_public"] = is_public
        if status is not None:
            patch["status"] = status
        if env_schema_json:
            patch["env_schema"] = json.loads(env_schema_json)
        if cmd_json:
            patch["cmd"] = json.loads(cmd_json)
        if json_spec_json:
            patch["json_spec"] = json.loads(json_spec_json)
        if registry_url is not None:
            patch["registry_url"] = registry_url

        if not patch:
            return json.dumps({"error": "no fields to update"})

        payload = MCPServerUpdate.model_validate(patch)

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
            server = await service.update_mcp_server(UUID(spec_id), payload)
            if not server:
                return json.dumps({"error": "MCP server spec not found"})
            return json.dumps(_serialize_server(server), default=str)

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
        async with platform_read_context() as (
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
                    "items": [_serialize_server(s) for s in servers],
                    "total": total,
                },
                default=str,
            )

    @tool_method
    async def get_spec(self, spec_id: str) -> str:
        """Get an MCP server spec (template) by ID."""
        async with platform_read_context() as (
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
            payload = _serialize_server(server)
            payload["env_schema"] = server.env_schema
            payload["registry_url"] = server.registry_url
            return json.dumps(payload, default=str)

    @tool_method
    async def delete_spec(self, spec_id: str) -> str:
        """Delete an MCP server spec (template) by ID."""
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

    # ------------------------------------------------------------------
    # Instances (configured deployments of a spec)
    # ------------------------------------------------------------------

    @tool_method
    async def create(
        self,
        name: str,
        json_spec_json: str,
        server_spec_id: str,
        description: str | None = None,
        auth_config_id: str | None = None,
    ) -> str:
        """Create a new MCP server instance.

        Args:
            name: Display name for the instance (unique per workspace).
            json_spec_json: JSON-encoded connection configuration. Must include
                ``type`` (``url`` | ``docker`` | ``command``);
                other keys depend on type.
            description: Optional human-readable description.
            server_spec_id: ID of an existing MCP server spec.
            auth_config_id: Optional MCPAuthConfig UUID for OAuth/credentials.
        """
        spec = json.loads(json_spec_json) if json_spec_json else {}
        payload = MCPServerInstanceCreate(
            name=name,
            description=description,
            server_spec_id=server_spec_id,
            json_spec=spec,
            auth_config_id=auth_config_id,
        )

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
            instance = await service.create_instance(payload)
            if not instance:
                return json.dumps({"error": "Failed to create MCP server instance"})
            return json.dumps(_serialize_instance(instance), default=str)

    @tool_method
    async def update(
        self,
        instance_id: str,
        name: str | None = None,
        description: str | None = None,
        json_spec_json: str = "",
    ) -> str:
        """Update fields on an existing MCP server instance."""
        patch: dict[str, Any] = {}
        if name is not None:
            patch["name"] = name
        if description is not None:
            patch["description"] = description
        if json_spec_json:
            patch["json_spec"] = json.loads(json_spec_json)

        if not patch:
            return json.dumps({"error": "no fields to update"})

        payload = MCPServerInstanceUpdate.model_validate(patch)

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
            instance = await service.update_instance(UUID(instance_id), payload)
            if not instance:
                return json.dumps({"error": "MCP server instance not found"})
            return json.dumps(_serialize_instance(instance), default=str)

    @tool_method
    async def list(self) -> str:
        """List all MCP server instances in the workspace."""
        async with platform_read_context() as (
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
                [_serialize_instance(i) for i in instances],
                default=str,
            )

    @tool_method
    async def get(self, instance_id: str) -> str:
        """Get details of an MCP server instance."""
        async with platform_read_context() as (
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
            payload = _serialize_instance(instance)
            payload["last_dispatch"] = instance.last_dispatch
            payload["tools"] = instance.tools
            return json.dumps(payload, default=str)

    @tool_method
    async def delete_instance(self, instance_id: str) -> str:
        """Delete an MCP server instance."""
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
