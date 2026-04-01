"""MCPToolAdapter — converts BaseTool/Toolset instances into MCP tool registrations.

Adapter pattern (GoF): bridges the internal tool interface to the MCP SDK's
FastMCP server. Each @tool_method becomes a separate MCP tool with
resource-first naming: ``{toolset.name}_{method_name}``.
"""

import inspect
import json
import logging
from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..tools.base_tool import BaseTool
from ..tools.decorator_tool import Toolset

logger = logging.getLogger(__name__)


class MCPToolAdapter:
    """Adapts BaseTool/Toolset instances to MCP SDK tool registrations."""

    def __init__(self, server: FastMCP):
        self._server = server

    def register_toolset(self, toolset: Toolset) -> None:
        """Register all @tool_method methods of a Toolset as individual MCP tools.

        Each method becomes a separate MCP tool named ``{toolset.name}_{method_name}``.
        """
        for method_name, method in toolset._tool_methods.items():
            tool_name = f"{toolset.name}_{method_name}"
            description = getattr(method, "_tool_description", f"{method_name}")
            handler = self._make_method_handler(toolset, method)

            self._server.add_tool(handler, name=tool_name, description=description)
            logger.debug(f"Registered MCP tool: {tool_name}")

        logger.info(
            f"Registered toolset '{toolset.name}' with {len(toolset._tool_methods)} MCP tools"
        )

    def register_tool(self, tool: BaseTool) -> None:
        """Register a single BaseTool as an MCP tool."""
        handler = self._make_tool_handler(tool)
        self._server.add_tool(handler, name=tool.name, description=tool.description)
        logger.debug(f"Registered MCP tool: {tool.name}")

    @staticmethod
    def _make_method_handler(toolset: Toolset, method: Callable) -> Callable:
        """Create an async handler function for a Toolset method.

        The handler preserves the original method's signature (minus ``self``)
        so the MCP SDK can introspect parameters and build JSON Schema.
        """
        is_async = inspect.iscoroutinefunction(method)

        async def handler(**kwargs: Any) -> str:
            if is_async:
                result = await method(**kwargs)
            else:
                result = method(**kwargs)
            if isinstance(result, str):
                return result
            return json.dumps(result, default=str)

        # Copy signature from original method, removing 'self'
        sig = inspect.signature(method)
        params = [p for name, p in sig.parameters.items() if name != "self"]
        handler.__signature__ = sig.replace(parameters=params)

        # Copy type hints (excluding 'self' and 'return')
        hints = {}
        for key, val in getattr(method, "__annotations__", {}).items():
            if key != "self":
                hints[key] = val
        # Force return type to str for MCP
        hints["return"] = str
        handler.__annotations__ = hints

        handler.__name__ = method.__name__
        handler.__qualname__ = method.__qualname__
        handler.__doc__ = method.__doc__

        return handler

    @staticmethod
    def _make_tool_handler(tool: BaseTool) -> Callable:
        """Create an async handler function for a BaseTool."""

        async def handler(**kwargs: Any) -> str:
            result = await tool.execute(**kwargs)
            if result.get("success"):
                data = result.get("result")
                return data if isinstance(data, str) else json.dumps(data, default=str)
            error = result.get("error", "Unknown error")
            return json.dumps({"error": error})

        # Build signature from tool's OpenAI schema
        schema = tool.get_schema()
        params_schema = schema.get("parameters", {})
        properties = params_schema.get("properties", {})
        required = set(params_schema.get("required", []))

        # Create inspect.Parameter objects from JSON schema
        params = []
        annotations = {"return": str}
        for param_name, param_info in properties.items():
            json_type = param_info.get("type", "string")
            py_type = _json_type_to_python(json_type)
            annotations[param_name] = py_type

            default = inspect.Parameter.empty if param_name in required else None
            params.append(
                inspect.Parameter(
                    param_name,
                    inspect.Parameter.KEYWORD_ONLY,
                    default=default,
                    annotation=py_type,
                )
            )

        handler.__signature__ = inspect.Signature(params)
        handler.__annotations__ = annotations
        handler.__name__ = tool.name
        handler.__doc__ = tool.description

        return handler


def _json_type_to_python(json_type: str) -> type:
    """Map JSON Schema type to Python type for MCP SDK introspection."""
    return {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }.get(json_type, str)
