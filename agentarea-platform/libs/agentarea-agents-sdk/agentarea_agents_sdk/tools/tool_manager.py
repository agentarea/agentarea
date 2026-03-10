"""Service for managing and discovering available tools."""

import logging
from typing import Any
from uuid import UUID

from .a2a_tool_factory import A2AAgentToolFactory
from .base_tool import ToolRegistry
from .code_tools_loader import create_code_tool_instance
from .completion_tool import CompletionTool
from .mcp_tool import MCPToolFactory

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
                # MCP tool - find instance by name
                mcp_tools = await self._discover_mcp_tools_by_name(
                    tool_name, settings.get("allowed_tools", []), mcp_server_instance_service
                )
                for mcp_tool in mcp_tools:
                    all_tools.append(mcp_tool.get_openai_function_definition())

            elif tool_type == "agent":
                # Agent-to-agent tool via A2A protocol
                if not agent_service or not base_url:
                    logger.warning(
                        f"Skipping agent tool '{tool_name}': "
                        "agent_service or base_url not provided"
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
            # Find instance by name
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
            logger.error(f"Failed to get tools from MCP instance {instance_name}: {e}")

        return all_mcp_tools

    def register_tool(self, tool) -> None:
        """Register a custom tool."""
        self.registry.register(tool)

    def get_registry(self) -> ToolRegistry:
        """Get the tool registry."""
        return self.registry
