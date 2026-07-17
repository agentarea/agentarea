"""MCP tool wrapper using the base tool interface."""

import logging
import os
from inspect import isawaitable
from typing import Any
from uuid import UUID

from .base_tool import BaseTool, ToolExecutionError

logger = logging.getLogger(__name__)


def _lazy_mcp_provisioning_enabled() -> bool:
    return os.getenv("MCP_LAZY_PROVISIONING_ENABLED", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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
        """Execute the MCP tool by delegating to the service's ``execute_tool``.

        The service is responsible for URL/transport resolution, auth, and
        bundle dispatch — this wrapper just adapts kwargs → (instance_id,
        tool_name, tool_args) and normalises the return shape.
        """
        service_execute = getattr(self.mcp_server_instance_service, "execute_tool", None)
        if not callable(service_execute):
            raise ToolExecutionError(
                self.name,
                "MCP server instance service does not implement execute_tool",
            )

        try:
            logger.info(
                "Executing MCP tool via service: instance=%s, tool=%s",
                self.server_instance_id,
                self.name,
            )
            execute_result = service_execute(
                self.server_instance_id,
                self.name,
                kwargs,
            )
            result = await execute_result if isawaitable(execute_result) else execute_result
            if not isinstance(result, dict):
                result = {"success": True, "result": result}
            result.setdefault("tool_name", self.name)
            result.setdefault("server_instance_id", str(self.server_instance_id))
            result.setdefault("success", True)
            result.setdefault("error", None)
            return result
        except ToolExecutionError:
            raise
        except Exception as e:
            logger.error("MCP tool execution failed for %s: %s", self.name, e, exc_info=True)
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
            verification = getattr(server_instance, "verification", None) or {}
            status = verification.get("status") or getattr(server_instance, "status", None)
            json_spec = getattr(server_instance, "json_spec", None) or {}
            tools_data = getattr(server_instance, "tools", None) or json_spec.get("available_tools")
            # running/connected are container runtime statuses; succeeded is the
            # verification payload status for URL instances.
            lazy_with_declared_tools = (
                _lazy_mcp_provisioning_enabled()
                and bool(json_spec.get("lazy_provisioning"))
                and bool(tools_data)
            )
            if status not in ("running", "connected", "succeeded") and not lazy_with_declared_tools:
                logger.info(
                    "MCP instance not verified-succeeded (status=%s); "
                    "this is expected transient during async creation — skipping tool discovery",
                    status,
                )
                return []

            # Read discovered tools from the dedicated column first. Older rows
            # may still carry them in json_spec.available_tools.
            if not tools_data:
                # Fallback: try service discovery methods
                for method_name in ["list_tools", "get_tools", "discover_tools"]:
                    fn = getattr(mcp_server_instance_service, method_name, None)
                    if callable(fn):
                        try:
                            call_result = fn(server_instance_id)
                            maybe_tools = (
                                await call_result if isawaitable(call_result) else call_result
                            )
                            if maybe_tools:
                                tools_data = maybe_tools
                                break
                        except Exception as e:
                            logger.warning(
                                f"Service.{method_name} failed for {server_instance_id}: {e}"
                            )

            if not tools_data:
                logger.warning(f"No tools found for MCP server instance {server_instance_id}")
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
                    description = t.get("description") or f"MCP tool: {name}"
                    # Support different schema keys
                    schema = (
                        t.get("inputSchema")
                        or t.get("schema")
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
