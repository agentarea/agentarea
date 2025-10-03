"""Decorator-based tool interface for automatic schema generation."""

import inspect
from abc import ABC
from collections.abc import Callable
from typing import Any, get_type_hints

from .base_tool import BaseTool


def tool_method(func: Callable = None):
    """Decorator to mark a method as a tool function.

    The description is automatically extracted from the method's docstring.
    Can be used as @tool_method or @tool_method()
    """

    def decorator(f: Callable) -> Callable:
        f._is_tool_method = True
        # Extract description from docstring
        if f.__doc__:
            # Get first line of docstring as description
            f._tool_description = f.__doc__.strip().split("\n")[0]
        else:
            f._tool_description = f"Method: {f.__name__}"
        return f

    # Support both @tool_method and @tool_method()
    if func is None:
        return decorator
    else:
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
        """Get toolset name from class name (snake_case)."""
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
        return self.__class__.__doc__ or f"Tool: {self.name}"

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
                            "description": f"[For {method_name}] {param_schema.get('description', '')}",
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

        # Map Python types to JSON schema types
        if type_hint is str or type_hint == str | None:
            schema["type"] = "string"
        elif type_hint is int or type_hint == int | None:
            schema["type"] = "integer"
        elif type_hint is float or type_hint == float | None:
            schema["type"] = "number"
        elif type_hint is bool or type_hint == bool | None:
            schema["type"] = "boolean"
        elif type_hint is list:
            schema["type"] = "array"
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
                        "result": f"Invalid action. Available actions: {list(self._tool_methods.keys())}",
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
