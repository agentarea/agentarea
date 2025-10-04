"""Base tool interface for unified tool handling."""

from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """Base class for all tools in the agentic system.

    This provides a unified interface for both built-in tools (like completion)
    and external tools (like MCP tools), following patterns from frameworks
    like LangChain, AutoGen, and CrewAI.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name for identification."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what the tool does."""
        pass

    @abstractmethod
    def get_schema(self) -> dict[str, Any]:
        """Get the OpenAI function schema for this tool."""
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> dict[str, Any]:
        """Execute the tool with given arguments.

        Args:
            **kwargs: Tool-specific arguments

        Returns:
            Dict containing execution results with standard format:
            {
                "success": bool,
                "result": Any,
                "error": str | None,
                "tool_name": str
            }
        """
        pass

    def get_openai_function_definition(self) -> dict[str, Any]:
        """Get OpenAI-compatible function definition.

        This is a convenience method that wraps get_schema() in the
        OpenAI function calling format.
        """
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, **self.get_schema()},
        }


class ToolExecutionError(Exception):
    """Exception raised when tool execution fails."""

    def __init__(self, tool_name: str, message: str, original_error: Exception | None = None):
        self.tool_name = tool_name
        self.original_error = original_error
        super().__init__(f"Tool '{tool_name}' execution failed: {message}")


class ToolRegistry:
    """Registry for managing available tools."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool in the registry."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_openai_functions(self) -> list[dict[str, Any]]:
        """Get OpenAI function definitions for all registered tools."""
        return [tool.get_openai_function_definition() for tool in self._tools.values()]
