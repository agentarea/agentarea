"""Service for managing and discovering available tools."""

import logging
from typing import Any
from uuid import UUID

from ..tools.base_tool import ToolRegistry
from ..tools.completion_tool import CompletionTool
from ..tools.mcp_tool import MCPToolFactory

logger = logging.getLogger(__name__)


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
