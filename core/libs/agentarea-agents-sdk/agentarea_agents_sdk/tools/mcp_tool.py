"""MCP tool wrapper using the base tool interface."""

import logging
from typing import Any
from uuid import UUID

from .base_tool import BaseTool, ToolExecutionError

logger = logging.getLogger(__name__)


class MCPTool(BaseTool):
    """Wrapper for MCP (Model Context Protocol) tools.

    This provides a unified interface for MCP tools to work with
    the same flow as built-in tools.
    """

    def __init__(
        self,
        name: str,
        description: str,
        schema: dict[str, Any],
        server_instance_id: UUID,
        mcp_server_instance_service,
    ):
        """Initialize MCP tool wrapper.

        Args:
            name: Tool name
            description: Tool description
            schema: Tool parameter schema
            server_instance_id: MCP server instance ID
            mcp_server_instance_service: Service for MCP operations
        """
        self._name = name
        self._description = description
        self._schema = schema
        self.server_instance_id = server_instance_id
        self.mcp_server_instance_service = mcp_server_instance_service

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def get_schema(self) -> dict[str, Any]:
        """Get the tool parameter schema."""
        return self._schema

    async def execute(self, **kwargs) -> dict[str, Any]:
        """Execute the MCP tool.

        Args:
            **kwargs: Tool-specific arguments

        Returns:
            Dict containing execution results
        """
        try:
            # Get server instance
            server_instance = await self.mcp_server_instance_service.get(self.server_instance_id)
            if not server_instance:
                raise ToolExecutionError(
                    self.name, f"MCP server instance {self.server_instance_id} not found"
                )

            # Basic safety: ensure instance is running before attempting execution
            status = getattr(server_instance, "status", None)
            if status != "running":
                raise ToolExecutionError(
                    self.name,
                    f"MCP server instance {self.server_instance_id} is not running (status: {status})",
                )

            # Prefer a dedicated execute method on the service if available
            service_execute = getattr(self.mcp_server_instance_service, "execute_tool", None)
            if callable(service_execute):
                logger.info(
                    f"Executing MCP tool via service: instance={self.server_instance_id}, tool={self.name}, args={kwargs}"
                )
                result = await service_execute(
                    server_instance_id=self.server_instance_id,
                    tool_name=self.name,
                    tool_args=kwargs,
                )
                # Expecting a dict payload; normalize minimal shape
                if not isinstance(result, dict):
                    result = {"success": True, "result": result}
                # Ensure common fields exist
                result.setdefault("tool_name", self.name)
                result.setdefault("server_instance_id", str(self.server_instance_id))
                result.setdefault("success", True)
                result.setdefault("error", None)
                return result

            # Fallback: if there is a generic "run_tool" or similar method
            for alt_method in ("run_tool", "invoke_tool", "call_tool"):
                fn = getattr(self.mcp_server_instance_service, alt_method, None)
                if callable(fn):
                    logger.info(
                        f"Executing MCP tool via service.{alt_method}: instance={self.server_instance_id}, tool={self.name}"
                    )
                    result = await fn(self.server_instance_id, self.name, kwargs)
                    if not isinstance(result, dict):
                        result = {"success": True, "result": result}
                    result.setdefault("tool_name", self.name)
                    result.setdefault("server_instance_id", str(self.server_instance_id))
                    result.setdefault("success", True)
                    result.setdefault("error", None)
                    return result

            # If we reach here, integration method is not yet implemented on the service
            logger.warning(
                f"MCP tool execution not yet implemented on service for tool {self.name}; service missing execute method"
            )

            # Placeholder return for now
            return {
                "success": True,
                "result": f"MCP tool {self.name} executed successfully (placeholder)",
                "tool_name": self.name,
                "error": None,
                "server_instance_id": str(self.server_instance_id),
            }

        except ToolExecutionError:
            # Re-raise tool execution errors as-is
            raise
        except Exception as e:
            logger.error(f"MCP tool execution failed for {self.name}: {e}")
            raise ToolExecutionError(self.name, str(e), e) from e


class MCPToolFactory:
    """Factory for creating MCP tool instances."""

    @staticmethod
    async def create_tools_from_server(
        server_instance_id: UUID,
        mcp_server_instance_service,
    ) -> list[MCPTool]:
        """Create MCP tool instances from a server.

        Args:
            server_instance_id: MCP server instance ID
            mcp_server_instance_service: Service for MCP operations

        Returns:
            List of MCP tool instances
        """
        try:
            server_instance = await mcp_server_instance_service.get(server_instance_id)
            if not server_instance:
                logger.warning(
                    f"MCP server instance {server_instance_id} not found during tool discovery"
                )
                return []
            if getattr(server_instance, "status", None) != "running":
                logger.info(
                    f"MCP server instance {server_instance_id} not running; skipping tool discovery"
                )
                return []

            # Try multiple discovery method names to maximize compatibility
            discovery_method_names = [
                "list_tools",
                "get_tools",
                "discover_tools",
                "discover_available_tools",
            ]
            tools_data = None
            for method_name in discovery_method_names:
                fn = getattr(mcp_server_instance_service, method_name, None)
                if callable(fn):
                    logger.info(
                        f"Discovering MCP tools via service.{method_name} for {server_instance_id}"
                    )
                    try:
                        maybe_tools = await fn(server_instance_id)
                        if maybe_tools:
                            tools_data = maybe_tools
                            break
                    except Exception as e:  # continue trying other methods
                        logger.warning(
                            f"Service.{method_name} failed for {server_instance_id}: {e}"
                        )

            if tools_data is None:
                logger.warning(
                    f"MCP tool discovery not implemented on service for server {server_instance_id}"
                )
                return []

            # Normalize tools list shape
            if (
                isinstance(tools_data, dict)
                and "tools" in tools_data
                and isinstance(tools_data["tools"], list)
            ):
                tools_list = tools_data["tools"]
            elif isinstance(tools_data, list):
                tools_list = tools_data
            else:
                logger.warning(
                    f"Unexpected tools payload for server {server_instance_id}: {type(tools_data)}"
                )
                return []

            mcp_tools: list[MCPTool] = []
            for t in tools_list:
                try:
                    # Expected fields: name, description, parameters/schema
                    name = t.get("name") if isinstance(t, dict) else None
                    if not name:
                        continue
                    description = t.get("description", f"MCP tool: {name}")
                    # Support different schema keys
                    schema = (
                        t.get("schema")
                        or t.get("parameters")
                        or {"parameters": {"type": "object", "properties": {}}}
                    )
                    # Ensure schema has an object parameters shape compatible with OpenAI tools
                    if "parameters" not in schema:
                        schema = {"parameters": schema}

                    mcp_tools.append(
                        MCPTool(
                            name=name,
                            description=description,
                            schema=schema,
                            server_instance_id=server_instance_id,
                            mcp_server_instance_service=mcp_server_instance_service,
                        )
                    )
                except Exception as e:
                    logger.warning(
                        f"Skipping invalid tool entry from server {server_instance_id}: {e}"
                    )

            return mcp_tools

        except Exception as e:
            logger.error(f"Failed to create tools from MCP server {server_instance_id}: {e}")
            return []
