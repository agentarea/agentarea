"""Service for managing and discovering available tools."""

import logging
from typing import Any
from uuid import UUID

from .a2a_tool_factory import A2AAgentToolFactory
from .base_tool import ToolRegistry
from .code_tools_loader import create_code_tool_instance
from .completion_tool import CompletionTool
from .mcp_tool import MCPToolFactory
from .openapi_tool import OpenAPIToolFactory
from .tool_provider import (
    AgentToolProvider,
    BuiltinToolProvider,
    CodeToolProvider,
    MCPToolProvider,
    OpenAPIToolProvider,
    ToolProvider,
)

logger = logging.getLogger(__name__)


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

        # Register built-in tools
        self.registry.register(CompletionTool())

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
        """Discover available tools for an agent.

        Args:
            agent_id: The agent ID
            tools_config: Agent's tools configuration (list of tool definitions)
            mcp_server_instance_service: Service for MCP server instances
            agent_service: Optional agent service for resolving agent-type tools
            base_url: Base URL for constructing A2A endpoints
            auth_token: Optional auth token for A2A calls

        Returns:
            List of available tool definitions (OpenAI format)
        """
        # Start with built-in tools
        all_tools = self.registry.get_openai_functions()

        if not tools_config:
            logger.info(f"No tools configured for agent {agent_id}")
            return all_tools

        for tool in tools_config:
            tool_type = tool.get("type")
            tool_name = tool.get("name")
            settings = tool.get("settings", {})

            if tool_type == "code":
                # Code-based tool
                disabled_methods = settings.get("disabled_methods", [])
                toolset_methods = (
                    {method: False for method in disabled_methods} if disabled_methods else {}
                )

                tool_instance = create_code_tool_instance(tool_name, toolset_methods)
                if tool_instance:
                    from .decorator_tool import Toolset, ToolsetAdapter

                    if isinstance(tool_instance, Toolset):
                        tool_instance = ToolsetAdapter(tool_instance)

                    all_tools.append(tool_instance.get_openai_function_definition())
                    logger.info(f"Added code tool: {tool_name}")
                else:
                    logger.warning(f"Unknown code tool requested: {tool_name}")

            elif tool_type == "mcp":
                # MCP tool - find instance by ID or name
                # Normalize allowed_tools: can be str[] or {tool_name, ...}[]
                raw_allowed = settings.get("allowed_tools") or []
                allowed_names = [
                    (t["tool_name"] if isinstance(t, dict) else t) for t in raw_allowed
                ]
                mcp_tools = await self._discover_mcp_tools_by_name(
                    tool_name, allowed_names, mcp_server_instance_service
                )
                for mcp_tool in mcp_tools:
                    all_tools.append(mcp_tool.get_openai_function_definition())

            elif tool_type == "agent":
                # Agent-to-agent tool via A2A protocol
                if not agent_service or not base_url:
                    logger.warning(
                        f"Skipping agent tool '{tool_name}': agent_service or base_url not provided"
                    )
                    continue

                a2a_tool = await A2AAgentToolFactory.create_tool(
                    agent_name=tool_name,
                    agent_service=agent_service,
                    base_url=base_url,
                    a2a_url_override=settings.get("a2a_url"),
                    auth_token=auth_token,
                    description_override=settings.get("description_override"),
                    task_service=task_service,
                    workspace_id=workspace_id,
                    user_id=user_id,
                )
                if a2a_tool:
                    all_tools.append(a2a_tool.get_openai_function_definition())
                    logger.info(f"Added agent tool: {tool_name}")

            elif tool_type == "openapi":
                # OpenAPI connection tool. Prefer settings.openapi_connection_id (UUID,
                # stable across renames) over tool.name so renaming a connection does
                # not break the agent link. Fall back to tool.name for legacy entries.
                connection_ref = settings.get("openapi_connection_id") or tool_name
                raw_allowed = settings.get("allowed_tools") or []
                allowed_names = [
                    (t["tool_name"] if isinstance(t, dict) else t) for t in raw_allowed
                ]
                openapi_tools = await self._discover_openapi_tools_by_name(
                    connection_ref, allowed_names, self._openapi_connection_service
                )
                for openapi_tool in openapi_tools:
                    all_tools.append(openapi_tool.get_openai_function_definition())

            else:
                logger.warning(
                    f"Unknown tool type: {tool_type}",
                    extra={"tool_config": tool},
                )

        logger.info(f"Discovered {len(all_tools)} tools for agent {agent_id}")
        return all_tools

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

        for tool in tools_config:
            tool_type = tool.get("type")
            tool_name = tool.get("name")
            settings = tool.get("settings", {})

            if tool_type == "code":
                disabled_methods = settings.get("disabled_methods", [])
                toolset_methods = (
                    {method: False for method in disabled_methods} if disabled_methods else {}
                )
                tool_instance = create_code_tool_instance(tool_name, toolset_methods)
                if tool_instance:
                    from .decorator_tool import Toolset, ToolsetAdapter

                    if isinstance(tool_instance, Toolset):
                        tool_instance = ToolsetAdapter(tool_instance)

                    providers.append(
                        CodeToolProvider(
                            name=tool_name,
                            tools=[tool_instance.get_openai_function_definition()],
                        )
                    )

            elif tool_type == "mcp":
                mcp_tools = await self._discover_mcp_tools_by_name(
                    tool_name, settings.get("allowed_tools", []), mcp_server_instance_service
                )
                if mcp_tools:
                    tool_defs = [t.get_openai_function_definition() for t in mcp_tools]
                    providers.append(
                        MCPToolProvider(
                            name=tool_name,
                            instance_id="",
                            tools=tool_defs,
                        )
                    )

            elif tool_type == "agent":
                if not agent_service or not base_url:
                    continue

                a2a_tool = await A2AAgentToolFactory.create_tool(
                    agent_name=tool_name,
                    agent_service=agent_service,
                    base_url=base_url,
                    a2a_url_override=settings.get("a2a_url"),
                    auth_token=auth_token,
                    description_override=settings.get("description_override"),
                    task_service=task_service,
                    workspace_id=workspace_id,
                    user_id=user_id,
                )
                if a2a_tool:
                    providers.append(
                        AgentToolProvider(
                            name=tool_name,
                            agent_id="",
                            tools=[a2a_tool.get_openai_function_definition()],
                        )
                    )

            elif tool_type == "openapi":
                # Prefer settings.openapi_connection_id (UUID, stable across renames).
                connection_ref = settings.get("openapi_connection_id") or tool_name
                raw_allowed = settings.get("allowed_tools") or []
                allowed_names = [
                    (t["tool_name"] if isinstance(t, dict) else t) for t in raw_allowed
                ]
                openapi_tools = await self._discover_openapi_tools_by_name(
                    connection_ref, allowed_names, self._openapi_connection_service
                )
                if openapi_tools:
                    tool_defs = [t.get_openai_function_definition() for t in openapi_tools]
                    providers.append(
                        OpenAPIToolProvider(
                            name=tool_name,
                            connection_id=str(connection_ref),
                            tools=tool_defs,
                        )
                    )

            else:
                logger.warning(
                    f"Unknown tool type: {tool_type}",
                    extra={"tool_config": tool},
                )

        logger.info(f"Discovered {len(providers)} tool providers for agent {agent_id}")
        return providers

    def register_tool(self, tool) -> None:
        """Register a custom tool."""
        self.registry.register(tool)

    def get_registry(self) -> ToolRegistry:
        """Get the tool registry."""
        return self.registry
