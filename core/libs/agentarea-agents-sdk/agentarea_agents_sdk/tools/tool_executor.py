"""Service for executing tools using unified tool interface."""

import logging
from typing import Any
from uuid import UUID

from .base_tool import BaseTool, ToolExecutionError, ToolRegistry
from .mcp_tool import MCPTool

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Service for executing tools using unified BaseTool interface."""

    def __init__(self):
        """Initialize tool executor with tool registry."""
        self.registry = ToolRegistry()

    async def execute_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        server_instance_id: UUID | None = None,
        mcp_server_instance_service=None,
    ) -> dict[str, Any]:
        """Execute a tool using the unified interface.

        Args:
            tool_name: Name of the tool to execute
            tool_args: Arguments for the tool
            server_instance_id: Optional MCP server instance ID (for MCP tools)
            mcp_server_instance_service: Service for MCP operations (for MCP tools)

        Returns:
            Dict containing execution results
        """
        try:
            # Try to find tool in registry first
            tool = self.registry.get(tool_name)

            if tool:
                logger.info(f"Executing registered tool '{tool_name}' with args: {tool_args}")
                return await tool.execute(**tool_args)

            # If not found, try to create MCP tool dynamically
            if server_instance_id and mcp_server_instance_service:
                mcp_tool = await self._create_mcp_tool(
                    tool_name, server_instance_id, mcp_server_instance_service
                )
                if mcp_tool:
                    logger.info(f"Executing MCP tool '{tool_name}' with args: {tool_args}")
                    return await mcp_tool.execute(**tool_args)

            # Tool not found
            logger.error(f"Tool '{tool_name}' not found in registry or MCP servers")
            raise ToolExecutionError(tool_name, "Tool not found")

        except ToolExecutionError:
            # Re-raise tool execution errors as-is
            raise
        except Exception as e:
            logger.error(f"Tool execution failed for '{tool_name}': {e}")
            raise ToolExecutionError(tool_name, str(e), e) from e

    async def _create_mcp_tool(
        self,
        tool_name: str,
        server_instance_id: UUID,
        mcp_server_instance_service,
    ) -> MCPTool | None:
        """Create an MCP tool dynamically."""
        try:
            # Ensure instance exists and is running
            instance = await mcp_server_instance_service.get(server_instance_id)
            if not instance:
                logger.warning(
                    f"MCP instance {server_instance_id} not found for dynamic tool creation"
                )
                return None
            if getattr(instance, "status", None) != "running":
                logger.info(
                    f"MCP instance {server_instance_id} is not running; cannot create tool '{tool_name}'"
                )
                return None

            # Attempt to fetch tool definitions from service
            discovery_methods = (
                "list_tools",
                "get_tools",
                "discover_tools",
                "discover_available_tools",
            )
            tools_payload = None
            for method in discovery_methods:
                fn = getattr(mcp_server_instance_service, method, None)
                if callable(fn):
                    try:
                        tools_payload = await fn(server_instance_id)
                        if tools_payload is not None:
                            break
                    except Exception as e:
                        logger.warning(f"Service.{method} failed for {server_instance_id}: {e}")

            tools_list: list[dict[str, Any]] = []
            if isinstance(tools_payload, dict) and isinstance(tools_payload.get("tools"), list):
                tools_list = tools_payload["tools"]
            elif isinstance(tools_payload, list):
                tools_list = tools_payload

            # Find the matching tool definition by name
            tool_def: dict[str, Any] | None = None
            for t in tools_list:
                if isinstance(t, dict) and t.get("name") == tool_name:
                    tool_def = t
                    break

            if tool_def:
                description = tool_def.get("description", f"MCP tool: {tool_name}")
                schema = (
                    tool_def.get("schema")
                    or tool_def.get("parameters")
                    or {"parameters": {"type": "object", "properties": {}}}
                )
                if "parameters" not in schema:
                    schema = {"parameters": schema}
                return MCPTool(
                    name=tool_name,
                    description=description,
                    schema=schema,
                    server_instance_id=server_instance_id,
                    mcp_server_instance_service=mcp_server_instance_service,
                )

            # Fallback placeholder tool if definition is unavailable
            logger.warning(
                f"Definition for MCP tool '{tool_name}' not found; creating placeholder tool"
            )
            return MCPTool(
                name=tool_name,
                description=f"MCP tool: {tool_name}",
                schema={"parameters": {"type": "object", "properties": {}}},
                server_instance_id=server_instance_id,
                mcp_server_instance_service=mcp_server_instance_service,
            )
        except Exception as e:
            logger.error(f"Failed to create MCP tool '{tool_name}': {e}")
            return None

    def register_tool(self, tool: BaseTool) -> None:
        """Register a tool in the executor's registry."""
        self.registry.register(tool)

    def get_available_tools(self) -> list[BaseTool]:
        """Get all available tools."""
        return self.registry.list_tools()

    def get_openai_functions(self) -> list[dict[str, Any]]:
        """Get OpenAI function definitions for all available tools."""
        return self.registry.get_openai_functions()
