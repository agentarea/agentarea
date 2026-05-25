"""Decorator-based tool interface for automatic schema generation."""

import inspect
import types
from abc import ABC
from collections.abc import Callable
from typing import Any, Union, get_args, get_origin, get_type_hints

from .base_tool import BaseTool
from .tool_definition import (
    ToolDefinition,
    ToolsetMetadata,
    build_tool_definition,
)


class ToolMethodMetadata:
    """Per-method metadata stamped by ``@tool_method(...)``."""

    __slots__ = ("display_name", "description", "requires_user_confirmation")

    def __init__(
        self,
        *,
        display_name: str = "",
        description: str = "",
        requires_user_confirmation: bool = False,
    ) -> None:
        self.display_name = display_name
        self.description = description
        self.requires_user_confirmation = requires_user_confirmation


def tool_method(
    func: Callable | None = None,
    *,
    display_name: str = "",
    description: str = "",
    requires_user_confirmation: bool = False,
):
    """Mark a method as a tool function.

    Description falls back to the docstring's first line. Optional metadata
    (``display_name``, ``requires_user_confirmation``) is exposed via
    ``method._tool_meta`` and surfaces in ``ToolsetMetadata``-driven UIs.

    Usage:
        @tool_method
        async def list(self): ...

        @tool_method(display_name="Create Agent")
        async def create(self, payload: AgentCreate) -> AgentSummary: ...
    """

    def decorator(f: Callable) -> Callable:
        f._is_tool_method = True
        if description:
            resolved_desc = description
        elif f.__doc__:
            resolved_desc = f.__doc__.strip().split("\n")[0]
        else:
            resolved_desc = f"Method: {f.__name__}"
        f._tool_description = resolved_desc
        f._tool_meta = ToolMethodMetadata(
            display_name=display_name or f.__name__.replace("_", " ").title(),
            description=resolved_desc,
            requires_user_confirmation=requires_user_confirmation,
        )
        return f

    if func is None:
        return decorator
    return decorator(func)


class Toolset(ABC):
    """Base class for toolsets using decorator-based method registration.

    A toolset represents a collection of related tool methods that can be called individually.
    This approach automatically generates schemas from method signatures and docstrings,
    eliminating the need for manual schema definition.
    """

    def __init__(self):
        """Initialize the tool and discover decorated methods."""
        self._tool_methods = self._discover_tool_methods()

    def _discover_tool_methods(self) -> dict[str, Callable]:
        """Discover all methods decorated with @tool_method."""
        methods = {}
        for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
            if hasattr(method, "_is_tool_method"):
                methods[name] = method
        return methods

    @property
    def name(self) -> str:
        """Toolset name.

        Prefers the last segment of ``@toolset(namespace="publisher/name")``
        when the metadata is set — necessary because mechanical CamelCase
        →snake_case mangles initialisms (``OpenAPIConnectionsToolset`` would
        become ``open_a_p_i_connections``). Falls back to a class-name
        derivation for legacy toolsets without ``@toolset``.
        """
        meta = getattr(self.__class__, "__toolset_meta__", None)
        if meta and meta.namespace:
            return meta.namespace.rsplit("/", 1)[-1]

        class_name = self.__class__.__name__
        # Convert CamelCase to snake_case
        import re

        snake_case = re.sub(r"(?<!^)(?=[A-Z])", "_", class_name).lower()
        # Remove common suffixes
        for suffix in ["_toolset", "_tool"]:
            if snake_case.endswith(suffix):
                snake_case = snake_case[: -len(suffix)]
                break
        return snake_case

    @property
    def description(self) -> str:
        """Get tool description from class docstring."""
        meta = getattr(self.__class__, "__toolset_meta__", None)
        if meta and meta.description:
            return meta.description
        return self.__class__.__doc__ or f"Tool: {self.name}"

    @property
    def metadata(self) -> ToolsetMetadata | None:
        """Class-level ``ToolsetMetadata`` if the class is decorated with ``@toolset``."""
        return getattr(self.__class__, "__toolset_meta__", None)

    def get_tool_definitions(self, *, name_prefix: str | None = None) -> list[ToolDefinition]:
        """One ``ToolDefinition`` per ``@tool_method`` — canonical MCP shape.

        ``name_prefix`` defaults to the toolset's ``name`` (snake_case class name)
        and is joined with the method name as ``{prefix}_{method}`` to match the
        existing MCPToolAdapter naming convention.
        """
        prefix = name_prefix if name_prefix is not None else self.name
        defs: list[ToolDefinition] = []
        for method_name, method in self._tool_methods.items():
            tool_name = f"{prefix}_{method_name}" if prefix else method_name
            defs.append(build_tool_definition(tool_name=tool_name, method=method))
        return defs

    def get_schema(self) -> dict[str, Any]:
        """Generate OpenAI function schema from decorated methods."""
        if len(self._tool_methods) == 1:
            # Single method - use its schema directly
            method_name, method = next(iter(self._tool_methods.items()))
            return self._generate_method_schema(method)
        else:
            # Multiple methods - create action parameter
            properties = {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": list(self._tool_methods.keys()),
                }
            }

            # Add parameters for each method
            for method_name, method in self._tool_methods.items():
                method_schema = self._generate_method_schema(method)
                if "parameters" in method_schema and "properties" in method_schema["parameters"]:
                    for param_name, param_schema in method_schema["parameters"][
                        "properties"
                    ].items():
                        properties[f"{method_name}_{param_name}"] = {
                            **param_schema,
                            "description": (
                                f"[For {method_name}] {param_schema.get('description', '')}"
                            ),
                        }

            return {
                "parameters": {"type": "object", "properties": properties, "required": ["action"]}
            }

    def _generate_method_schema(self, method: Callable) -> dict[str, Any]:
        """Generate schema for a single method."""
        sig = inspect.signature(method)
        type_hints = get_type_hints(method)

        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue

            param_schema = self._get_parameter_schema(param, type_hints.get(param_name))
            properties[param_name] = param_schema

            if param.default == inspect.Parameter.empty:
                required.append(param_name)

        return {"parameters": {"type": "object", "properties": properties, "required": required}}

    def _get_parameter_schema(self, param: inspect.Parameter, type_hint: Any) -> dict[str, Any]:
        """Generate schema for a single parameter."""
        schema = {"description": f"Parameter: {param.name}"}
        origin = get_origin(type_hint)
        args = get_args(type_hint)
        union_args = args if origin in (types.UnionType, Union) else ()
        if union_args and type(None) in union_args:
            non_none = [arg for arg in union_args if arg is not type(None)]
            type_hint = non_none[0] if non_none else Any
            origin = get_origin(type_hint)
            args = get_args(type_hint)

        # Map Python types to JSON schema types
        if type_hint is str or type_hint == str | None:
            schema["type"] = "string"
        elif type_hint is int or type_hint == int | None:
            schema["type"] = "integer"
        elif type_hint is float or type_hint == float | None:
            schema["type"] = "number"
        elif type_hint is bool or type_hint == bool | None:
            schema["type"] = "boolean"
        elif type_hint is list or origin is list:
            schema["type"] = "array"
            item_type = args[0] if args else str
            if item_type is int:
                schema["items"] = {"type": "integer"}
            elif item_type is float:
                schema["items"] = {"type": "number"}
            elif item_type is bool:
                schema["items"] = {"type": "boolean"}
            elif item_type is dict:
                schema["items"] = {"type": "object"}
            else:
                schema["items"] = {"type": "string"}
        elif type_hint is dict:
            schema["type"] = "object"
        else:
            schema["type"] = "string"  # Default fallback

        return schema

    async def execute(self, **kwargs) -> dict[str, Any]:
        """Execute the appropriate tool method based on parameters."""
        try:
            if len(self._tool_methods) == 1:
                # Single method - execute directly
                method_name, method = next(iter(self._tool_methods.items()))
                result = await self._execute_method(method, kwargs)
            else:
                # Multiple methods - use action parameter
                action = kwargs.get("action")
                if not action or action not in self._tool_methods:
                    return {
                        "success": False,
                        "result": (
                            f"Invalid action. Available actions: {list(self._tool_methods.keys())}"
                        ),
                        "tool_name": self.name,
                        "error": "Invalid action",
                    }

                method = self._tool_methods[action]
                # Filter kwargs for this specific method
                method_kwargs = self._filter_kwargs_for_method(action, kwargs)
                result = await self._execute_method(method, method_kwargs)

            return {"success": True, "result": result, "tool_name": self.name, "error": None}

        except Exception as e:
            return {
                "success": False,
                "result": f"Execution failed: {str(e)}",
                "tool_name": self.name,
                "error": str(e),
            }

    def _filter_kwargs_for_method(self, method_name: str, kwargs: dict) -> dict:
        """Filter kwargs to only include parameters for the specific method."""
        method = self._tool_methods[method_name]
        sig = inspect.signature(method)

        filtered_kwargs = {}
        for param_name in sig.parameters:
            if param_name == "self":
                continue

            # Check for method-specific parameter
            prefixed_name = f"{method_name}_{param_name}"
            if prefixed_name in kwargs:
                filtered_kwargs[param_name] = kwargs[prefixed_name]
            elif param_name in kwargs:
                filtered_kwargs[param_name] = kwargs[param_name]

        return filtered_kwargs

    async def _execute_method(self, method: Callable, kwargs: dict) -> Any:
        """Execute a single method with the given kwargs."""
        if inspect.iscoroutinefunction(method):
            return await method(**kwargs)
        else:
            return method(**kwargs)

    def get_openai_function_definition(self) -> dict[str, Any]:
        """Get OpenAI-compatible function definition."""
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, **self.get_schema()},
        }


# Adapter to make Toolset compatible with existing BaseTool interface
class ToolsetAdapter(BaseTool):
    """Adapter to make Toolset compatible with existing BaseTool interface."""

    def __init__(self, toolset: Toolset):
        self._toolset = toolset

    @property
    def name(self) -> str:
        return self._toolset.name

    @property
    def description(self) -> str:
        return self._toolset.description

    def get_schema(self) -> dict[str, Any]:
        return self._toolset.get_schema()

    async def execute(self, **kwargs) -> dict[str, Any]:
        return await self._toolset.execute(**kwargs)
