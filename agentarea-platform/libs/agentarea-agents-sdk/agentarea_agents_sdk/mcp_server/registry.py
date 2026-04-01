"""MCPToolRegistry — collects toolsets for bulk MCP registration.

Provides a convenience layer for gathering tools from multiple sources
(code_tools.yaml, platform services, custom toolsets) and registering
them all with an MCP server in one call.
"""

import logging

from ..tools.base_tool import BaseTool
from ..tools.decorator_tool import Toolset

logger = logging.getLogger(__name__)


class MCPToolRegistry:
    """Collects BaseTool/Toolset instances for MCP registration."""

    def __init__(self):
        self._tools: list[Toolset | BaseTool] = []

    def add(self, tool: Toolset | BaseTool) -> None:
        """Add a single tool or toolset."""
        self._tools.append(tool)

    def add_all(self, tools: list[Toolset | BaseTool]) -> None:
        """Add multiple tools/toolsets."""
        self._tools.extend(tools)

    def add_from_yaml(self, category_filter: str | None = None) -> None:
        """Load tools from code_tools.yaml and add them.

        Args:
            category_filter: If set, only load tools matching this category
                             (e.g. "platform", "utility").
        """
        from ..tools.code_tools_loader import create_code_tool_instance, get_code_tools_metadata

        metadata = get_code_tools_metadata()

        for tool_name, tool_info in metadata.items():
            if category_filter and tool_info.get("category") != category_filter:
                continue

            instance = create_code_tool_instance(tool_name)
            if instance:
                self._tools.append(instance)
                logger.debug(f"Loaded tool from YAML: {tool_name}")
            else:
                logger.warning(f"Failed to load tool: {tool_name}")

    @property
    def tools(self) -> list[Toolset | BaseTool]:
        """All registered tools."""
        return list(self._tools)

    def __len__(self) -> int:
        return len(self._tools)

    def tool_names(self) -> list[str]:
        """List names of all registered tools (for logging)."""
        names: list[str] = []
        for tool in self._tools:
            if isinstance(tool, Toolset):
                for method_name in tool._tool_methods:
                    names.append(f"{tool.name}_{method_name}")
            elif isinstance(tool, BaseTool):
                names.append(tool.name)
        return names
