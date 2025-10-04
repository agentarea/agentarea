"""Service for managing and discovering available tools."""

import logging
from typing import Any
from uuid import UUID

from .base_tool import ToolRegistry
from .builtin_tools_loader import (
    create_builtin_tool_instance,
    get_builtin_tools_metadata,
)
from .completion_tool import CompletionTool
from .mcp_tool import MCPToolFactory

logger = logging.getLogger(__name__)


def get_available_builtin_tools() -> dict[str, dict[str, Any]]:
    """Get available builtin tools with their metadata.

    Returns:
        Dict mapping tool names to their metadata
    """
    return get_builtin_tools_metadata()


class ToolManager:
    """Service for managing tool discovery and availability using unified tool interface."""

    def __init__(self):
        """Initialize tool manager with registry."""
        self.registry = ToolRegistry()

        # Register built-in tools
        self.registry.register(CompletionTool())

    async def discover_available_tools(
        self,
        agent_id: UUID,
        tools_config: dict[str, Any] | None,
        mcp_server_instance_service,
    ) -> list[dict[str, Any]]:
        """Discover available tools for an agent.

        Args:
            agent_id: The agent ID
            tools_config: Agent's tools configuration
            mcp_server_instance_service: Service for MCP server instances

        Returns:
            List of available tool definitions (OpenAI format)
        """
        # Start with built-in tools
        all_tools = self.registry.get_openai_functions()

        # Add builtin tools if specified in config
        if tools_config and tools_config.get("builtin_tools"):
            for tool_config in tools_config["builtin_tools"]:
                if isinstance(tool_config, dict):
                    tool_name = tool_config["tool_name"]
                    # Extract toolset method configuration if present
                    # Support both "enabled_methods" (old) and "disabled_methods" (new, preferred)
                    disabled_methods = tool_config.get("disabled_methods", {})
                    enabled_methods = tool_config.get("enabled_methods", {})

                    # Convert disabled_methods to constructor arguments (all True except disabled ones)
                    if disabled_methods:
                        toolset_methods = {method: False for method in disabled_methods.keys()}
                    elif enabled_methods:
                        # Legacy support for enabled_methods
                        toolset_methods = enabled_methods
                    else:
                        toolset_methods = {}
                else:
                    tool_name = tool_config
                    toolset_methods = {}

                tool_instance = create_builtin_tool_instance(tool_name, toolset_methods)
                if tool_instance:
                    # Check if tool is a Toolset - if so, wrap it in adapter for compatibility
                    from .decorator_tool import Toolset, ToolsetAdapter

                    if isinstance(tool_instance, Toolset):
                        tool_instance = ToolsetAdapter(tool_instance)

                    all_tools.append(tool_instance.get_openai_function_definition())
                    logger.info(f"Added builtin tool: {tool_name}")
                else:
                    logger.warning(f"Unknown builtin tool requested: {tool_name}")

        # Add tools from configured MCP servers
        if tools_config:
            mcp_server_ids = tools_config.get("mcp_servers", [])
            mcp_tools = await self._discover_mcp_tools(mcp_server_ids, mcp_server_instance_service)

            # Convert MCP tools to OpenAI function format
            for mcp_tool in mcp_tools:
                all_tools.append(mcp_tool.get_openai_function_definition())

        logger.info(f"Discovered {len(all_tools)} tools for agent {agent_id}")
        return all_tools

    async def _discover_mcp_tools(
        self,
        mcp_server_ids: list[str],
        mcp_server_instance_service,
    ) -> list:
        """Discover tools from MCP servers."""
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

    def register_tool(self, tool) -> None:
        """Register a custom tool."""
        self.registry.register(tool)

    def get_registry(self) -> ToolRegistry:
        """Get the tool registry."""
        return self.registry
