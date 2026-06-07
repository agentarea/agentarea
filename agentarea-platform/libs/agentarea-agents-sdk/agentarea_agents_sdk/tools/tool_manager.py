"""Service for managing and discovering available tools."""

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from .base_tool import ToolRegistry
from .completion_tool import CompletionTool
from .decorator_tool import ToolsetAdapter
from .mcp_tool import MCPToolFactory
from .openapi_tool import OpenAPIToolFactory, _slugify_name
from .tool_builders import (
    ToolBuildContext,
    build_tool_builder_registry,
    parse_tool_spec,
)
from .tool_provider import (
    BuiltinToolProvider,
    ToolProvider,
)

logger = logging.getLogger(__name__)


@dataclass
class DiscoveryResult:
    """Output of `discover_available_tools_split`.

    `explicit_tools` ships full OpenAI function definitions into the LLM
    context every call. `searchable_entries` are deferred — they live in
    workflow state for the `load_tools` meta-tool to reveal on demand. Each
    entry is a dict matching the ToolCandidate shape: name, description,
    connection_id, schema, source_type.
    """

    explicit_tools: list[dict[str, Any]] = field(default_factory=list)
    searchable_entries: list[dict[str, Any]] = field(default_factory=list)


class ToolManager:
    """Service for managing tool discovery and availability using unified tool interface."""

    def __init__(self, openapi_connection_service=None):
        """Initialize tool manager with registry.

        Args:
            openapi_connection_service: Optional OpenAPIConnectionService for resolving
                openapi-type tools. Existing callers that omit this arg continue to work.
        """
        self.registry = ToolRegistry()
        self._openapi_connection_service = openapi_connection_service
        # GoF Registry: tool type -> build strategy (see tool_builders.py).
        self._builders = build_tool_builder_registry()

        # Register built-in tools
        self.registry.register(ToolsetAdapter(CompletionTool()))

    async def discover_available_tools(
        self,
        agent_id: UUID,
        tools_config: list[dict[str, Any]] | None,
        mcp_server_instance_service,
        agent_service=None,
        base_url: str = "",
        auth_token: str | None = None,
        task_service=None,
        workspace_id: str | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Discover available tools for an agent (legacy flat-list API).

        Ignores `load_mode` and always returns full schemas for every tool —
        existing callers keep their current behavior. New code should use
        `discover_available_tools_split` to honor `load_mode`.
        """
        result = await self._discover(
            agent_id=agent_id,
            tools_config=tools_config,
            mcp_server_instance_service=mcp_server_instance_service,
            agent_service=agent_service,
            base_url=base_url,
            auth_token=auth_token,
            task_service=task_service,
            workspace_id=workspace_id,
            user_id=user_id,
            force_explicit=True,
        )
        return result.explicit_tools

    async def discover_available_tools_split(
        self,
        agent_id: UUID,
        tools_config: list[dict[str, Any]] | None,
        mcp_server_instance_service,
        agent_service=None,
        base_url: str = "",
        auth_token: str | None = None,
        task_service=None,
        workspace_id: str | None = None,
        user_id: str | None = None,
    ) -> DiscoveryResult:
        """Discover tools, honoring `settings.load_mode` per tool.

        For OpenAPI tools with `load_mode == "searchable"`, schemas go into
        `searchable_entries` (deferred pool) instead of `explicit_tools`.
        Other tool types and `load_mode == "explicit"` (or absent) preserve
        legacy behavior — full schemas in `explicit_tools`.
        """
        return await self._discover(
            agent_id=agent_id,
            tools_config=tools_config,
            mcp_server_instance_service=mcp_server_instance_service,
            agent_service=agent_service,
            base_url=base_url,
            auth_token=auth_token,
            task_service=task_service,
            workspace_id=workspace_id,
            user_id=user_id,
            force_explicit=False,
        )

    async def _discover(
        self,
        agent_id: UUID,
        tools_config: list[dict[str, Any]] | None,
        mcp_server_instance_service,
        agent_service,
        base_url: str,
        auth_token: str | None,
        task_service,
        workspace_id: str | None,
        user_id: str | None,
        force_explicit: bool,
    ) -> DiscoveryResult:
        """Shared discovery worker. Public methods select force_explicit."""
        result = DiscoveryResult(explicit_tools=list(self.registry.get_openai_functions()))

        if not tools_config:
            logger.info(f"No tools configured for agent {agent_id}")
            return result

        ctx = ToolBuildContext(
            manager=self,
            mcp_server_instance_service=mcp_server_instance_service,
            agent_service=agent_service,
            base_url=base_url,
            auth_token=auth_token,
            task_service=task_service,
            workspace_id=workspace_id,
            user_id=user_id,
            force_explicit=force_explicit,
        )
        for tool in tools_config:
            spec = parse_tool_spec(tool)
            if spec is None:
                continue
            builder = self._builders.get(tool.get("type"))
            if builder is None:
                logger.warning(f"Unknown tool type: {tool.get('type')}", extra={"tool_config": tool})
                continue
            await builder.add_explicit(spec, ctx, result)

        logger.info(
            "Discovered %d explicit tools and %d searchable entries for agent %s",
            len(result.explicit_tools),
            len(result.searchable_entries),
            agent_id,
        )
        return result

    async def _build_openapi_searchable_entries(
        self,
        connection_name_or_id: str,
        allowed_tools: list[str],
        openapi_connection_service,
    ) -> list[dict[str, Any]]:
        """Cheap path: read pre-parsed `available_tools` from the DB, no spec re-parse.

        Returns ToolCandidate-shaped dicts ready for the workflow's
        searchable pool: {name, description, connection_id, schema, source_type}.
        Schemas are pre-built so `load_tools` reveal becomes a dict lookup at
        runtime — no per-call connection refetch.
        """
        if not openapi_connection_service:
            logger.warning(
                "Skipping openapi tool %r: no openapi_connection_service provided",
                connection_name_or_id,
            )
            return []

        connection = await self._resolve_openapi_connection(
            connection_name_or_id, openapi_connection_service
        )
        if not connection:
            return []

        available = getattr(connection, "available_tools", None) or []
        allowed_set = set(allowed_tools) if allowed_tools else None

        entries: list[dict[str, Any]] = []
        for op in available:
            raw_name = op.get("name") or ""
            if not raw_name:
                continue
            if allowed_set is not None and raw_name not in allowed_set:
                continue
            slugified = _slugify_name(raw_name)
            description = op.get("description") or f"OpenAPI operation {raw_name}"
            schema = {
                "type": "function",
                "function": {
                    "name": slugified,
                    "description": description,
                    "parameters": op.get("inputSchema") or {"type": "object", "properties": {}},
                },
            }
            entries.append(
                {
                    "name": slugified,
                    "description": description,
                    "connection_id": str(getattr(connection, "id", "") or connection_name_or_id),
                    "schema": schema,
                    "source_type": "openapi",
                }
            )
        return entries

    async def _resolve_openapi_connection(
        self,
        connection_name_or_id: str,
        openapi_connection_service,
    ):
        """Resolve a UUID-or-name reference to an OpenAPIConnection record.

        Mirrors the resolution path used by `OpenAPIToolFactory.create_tools_from_connection`
        so legacy and searchable paths agree on which connection they pick.
        """
        try:
            try:
                uuid_val = UUID(str(connection_name_or_id))
                conn = await openapi_connection_service.get_connection(uuid_val)
                if conn:
                    return conn
            except (ValueError, AttributeError):
                pass
            connections, _ = await openapi_connection_service.list_connections(
                search=str(connection_name_or_id)
            )
            for conn in connections:
                if conn.name == str(connection_name_or_id):
                    return conn
        except Exception as e:
            logger.error(
                "Failed to resolve OpenAPI connection %r: %s",
                connection_name_or_id,
                e,
                exc_info=True,
            )
        logger.warning("OpenAPI connection not found: %r", connection_name_or_id)
        return None

    async def _discover_mcp_tools(
        self,
        mcp_server_ids: list[str],
        mcp_server_instance_service,
    ) -> list:
        """Discover tools from MCP servers by UUID (legacy format)."""
        all_mcp_tools = []

        for server_id in mcp_server_ids:
            try:
                server_uuid = UUID(str(server_id))
                mcp_tools = await MCPToolFactory.create_tools_from_server(
                    server_uuid, mcp_server_instance_service
                )
                all_mcp_tools.extend(mcp_tools)

            except Exception as e:
                logger.error(f"Failed to get tools from MCP server {server_id}: {e}")
                continue

        return all_mcp_tools

    async def _discover_mcp_tools_by_name(
        self,
        instance_name: str,
        allowed_tools: list[str],
        mcp_server_instance_service,
    ) -> list:
        """Discover tools from MCP server instance by name.

        Args:
            instance_name: Name of the MCP server instance
            allowed_tools: List of tool names to allow (empty means all)
            mcp_server_instance_service: Service for MCP server instances

        Returns:
            List of MCP tools
        """
        all_mcp_tools = []

        try:
            # Find instance by ID (UUID) or by name
            instance = None
            try:
                from uuid import UUID as _UUID

                instance_uuid = _UUID(instance_name)
                instance = await mcp_server_instance_service.get(instance_uuid)
            except (ValueError, TypeError):
                pass  # Not a UUID — fall through to name lookup

            if not instance:
                instance = await mcp_server_instance_service.get_by_name(instance_name)

            if not instance:
                logger.warning(f"MCP server instance not found: {instance_name}")
                return all_mcp_tools

            # Get tools from the instance
            mcp_tools = await MCPToolFactory.create_tools_from_server(
                instance.id, mcp_server_instance_service
            )

            # Filter by allowed_tools if specified
            if allowed_tools:
                mcp_tools = [tool for tool in mcp_tools if tool.name in allowed_tools]

            all_mcp_tools.extend(mcp_tools)
            logger.info(f"Discovered {len(mcp_tools)} tools from MCP instance: {instance_name}")

        except Exception as e:
            logger.error(
                f"Failed to get tools from MCP instance {instance_name}: {e}", exc_info=True
            )

        return all_mcp_tools

    async def _discover_openapi_tools_by_name(
        self,
        connection_name: str,
        allowed_tools: list[str],
        openapi_connection_service,
    ) -> list:
        """Discover tools from an OpenAPI connection by name or UUID.

        Args:
            connection_name: Name or UUID string of the OpenAPI connection.
            allowed_tools: List of tool names to allow (empty means all).
            openapi_connection_service: Service for OpenAPI connections.

        Returns:
            List of OpenAPITool instances.
        """
        if not openapi_connection_service:
            logger.warning(
                f"Skipping openapi tool '{connection_name}': no openapi_connection_service provided"
            )
            return []

        try:
            tools = await OpenAPIToolFactory.create_tools_from_connection(
                connection_name_or_id=connection_name,
                allowed_tools=allowed_tools if allowed_tools else None,
                openapi_connection_service=openapi_connection_service,
            )
            logger.info(f"Discovered {len(tools)} tools from OpenAPI connection: {connection_name}")
            return tools
        except Exception as e:
            logger.error(
                f"Failed to get tools from OpenAPI connection {connection_name}: {e}",
                exc_info=True,
            )
            return []

    async def discover_tool_providers(
        self,
        agent_id: UUID,
        tools_config: list[dict[str, Any]] | None,
        mcp_server_instance_service,
        agent_service=None,
        base_url: str = "",
        auth_token: str | None = None,
        task_service=None,
        workspace_id: str | None = None,
        user_id: str | None = None,
    ) -> list[ToolProvider]:
        """Discover tool providers for progressive disclosure.

        Same inputs as discover_available_tools, but returns ToolProvider
        instances instead of flat tool definitions. Used by DYNAMIC strategy.
        """
        providers: list[ToolProvider] = []

        # Built-in tools (completion, etc.)
        builtin_tools = self.registry.get_openai_functions()
        if builtin_tools:
            providers.append(BuiltinToolProvider(name="builtin", tools=builtin_tools))

        if not tools_config:
            return providers

        ctx = ToolBuildContext(
            manager=self,
            mcp_server_instance_service=mcp_server_instance_service,
            agent_service=agent_service,
            base_url=base_url,
            auth_token=auth_token,
            task_service=task_service,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        for tool in tools_config:
            spec = parse_tool_spec(tool)
            if spec is None:
                continue
            builder = self._builders.get(tool.get("type"))
            if builder is None:
                logger.warning(
                    f"Unknown tool type: {tool.get('type')}",
                    extra={"tool_config": tool},
                )
                continue
            await builder.add_provider(spec, ctx, providers)

        logger.info(f"Discovered {len(providers)} tool providers for agent {agent_id}")
        return providers

    def register_tool(self, tool) -> None:
        """Register a custom tool."""
        self.registry.register(tool)

    def get_registry(self) -> ToolRegistry:
        """Get the tool registry."""
        return self.registry
