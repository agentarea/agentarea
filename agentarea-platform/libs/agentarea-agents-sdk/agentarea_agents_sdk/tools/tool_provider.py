"""ToolProvider protocol and concrete implementations.

Follows Strategy + Proxy patterns (GoF) for tool source abstraction.
Any source of tools (MCP, code, agent, etc.) implements ToolProvider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class CatalogEntry:
    """Lightweight proxy for full tool definitions.

    Used in the system prompt to give the LLM awareness of available tool
    sources without loading full schemas into context.
    """

    name: str
    provider_type: str  # "mcp", "code", "agent", "builtin"
    tool_names: list[str] = field(default_factory=list)
    description: str = ""


@runtime_checkable
class ToolProvider(Protocol):
    """Abstraction for any source of tools (OCP + DIP).

    Concrete implementations wrap MCP servers, code tools, agent tools, etc.
    The workflow never depends on concrete providers — only on this protocol.
    """

    @property
    def name(self) -> str:
        """Unique name for this tool source."""
        ...

    @property
    def provider_type(self) -> str:
        """Type identifier: 'mcp', 'code', 'agent', 'builtin'."""
        ...

    def get_catalog_entry(self) -> CatalogEntry:
        """Return a lightweight catalog entry for system prompt."""
        ...

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return full OpenAI-format tool definitions."""
        ...


class MCPToolProvider:
    """ToolProvider backed by an MCP server instance."""

    def __init__(
        self,
        name: str,
        instance_id: str,
        tools: list[dict[str, Any]],
        description: str = "",
    ):
        self._name = name
        self._instance_id = instance_id
        self._tools = tools
        self._description = description or f"MCP server: {name}"

    @property
    def name(self) -> str:
        return self._name

    @property
    def provider_type(self) -> str:
        return "mcp"

    def get_catalog_entry(self) -> CatalogEntry:
        tool_names = [t.get("function", {}).get("name", "unknown") for t in self._tools]
        return CatalogEntry(
            name=self._name,
            provider_type="mcp",
            tool_names=tool_names,
            description=self._description,
        )

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return self._tools


class CodeToolProvider:
    """ToolProvider backed by code-defined tools."""

    def __init__(
        self,
        name: str,
        tools: list[dict[str, Any]],
        description: str = "",
    ):
        self._name = name
        self._tools = tools
        self._description = description or f"Code tools: {name}"

    @property
    def name(self) -> str:
        return self._name

    @property
    def provider_type(self) -> str:
        return "code"

    def get_catalog_entry(self) -> CatalogEntry:
        tool_names = [t.get("function", {}).get("name", "unknown") for t in self._tools]
        return CatalogEntry(
            name=self._name,
            provider_type="code",
            tool_names=tool_names,
            description=self._description,
        )

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return self._tools


class AgentToolProvider:
    """ToolProvider backed by A2A agent delegation."""

    def __init__(
        self,
        name: str,
        agent_id: str,
        tools: list[dict[str, Any]],
        description: str = "",
    ):
        self._name = name
        self._agent_id = agent_id
        self._tools = tools
        self._description = description or f"Agent: {name}"

    @property
    def name(self) -> str:
        return self._name

    @property
    def provider_type(self) -> str:
        return "agent"

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def get_catalog_entry(self) -> CatalogEntry:
        tool_names = [t.get("function", {}).get("name", "unknown") for t in self._tools]
        return CatalogEntry(
            name=self._name,
            provider_type="agent",
            tool_names=tool_names,
            description=self._description,
        )

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return self._tools


class OpenAPIToolProvider:
    """ToolProvider backed by an OpenAPI connection."""

    def __init__(
        self,
        name: str,
        connection_id: str,
        tools: list[dict[str, Any]],
        description: str = "",
    ):
        self._name = name
        self._connection_id = connection_id
        self._tools = tools
        self._description = description or f"OpenAPI connection: {name}"

    @property
    def name(self) -> str:
        return self._name

    @property
    def provider_type(self) -> str:
        return "openapi"

    def get_catalog_entry(self) -> CatalogEntry:
        tool_names = [t.get("function", {}).get("name", "unknown") for t in self._tools]
        return CatalogEntry(
            name=self._name,
            provider_type="openapi",
            tool_names=tool_names,
            description=self._description,
        )

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return self._tools


class BuiltinToolProvider:
    """ToolProvider for built-in tools (completion, etc.)."""

    def __init__(self, name: str, tools: list[dict[str, Any]]):
        self._name = name
        self._tools = tools

    @property
    def name(self) -> str:
        return self._name

    @property
    def provider_type(self) -> str:
        return "builtin"

    def get_catalog_entry(self) -> CatalogEntry:
        tool_names = [t.get("function", {}).get("name", "unknown") for t in self._tools]
        return CatalogEntry(
            name=self._name,
            provider_type="builtin",
            tool_names=tool_names,
            description="Built-in tools",
        )

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return self._tools
