"""Serve a subset of an MCP server's toolsets per request.

A server that flattens every toolset into one tool list hands a harness all of
them at once. A request can instead name the toolsets it wants — the ``toolsets``
query parameter on a mount, or a registered client's attachments — and then
lists, and may call, only their tools.
"""

import json
import logging
from collections.abc import Collection, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from mcp.types import CallToolResult, TextContent, Tool
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

TOOLSETS_QUERY_PARAM = "toolsets"

# Tool names the current request may see; None serves every registered tool.
_selected_tools_var: ContextVar[frozenset[str] | None] = ContextVar(
    "mcp_selected_tools", default=None
)


class UnknownToolsetError(ValueError):
    """A selection names a toolset, or a method of one, that the server lacks."""


@dataclass(frozen=True)
class RegisteredToolset:
    """A toolset as served: its tool-name prefix, namespace, and MCP tool names."""

    name: str
    namespace: str
    # method name -> MCP tool name
    tools: Mapping[str, str]


class ToolsetMCPServer(MCPServer):
    """An MCPServer whose tools a request can narrow to some of its toolsets.

    Outside :func:`selected_tools` every tool is served. Inside it, tools
    outside the selection are neither listed nor callable: a call to one fails
    exactly as a call to a tool the server never had.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._toolsets: dict[str, RegisteredToolset] = {}
        self._by_namespace: dict[str, RegisteredToolset] = {}

    def register_toolset(self, toolset: RegisteredToolset) -> None:
        self._toolsets[toolset.name] = toolset
        self._by_namespace[toolset.namespace] = toolset

    @property
    def toolsets(self) -> Mapping[str, RegisteredToolset]:
        """Registered toolsets by name, in registration order."""
        return self._toolsets

    def resolve(self, reference: str) -> RegisteredToolset:
        """The toolset *reference* names, by name (``runs``) or namespace."""
        toolset = self._toolsets.get(reference) or self._by_namespace.get(reference)
        if toolset is None:
            raise UnknownToolsetError(
                f"Unknown toolset '{reference}'. Available: {', '.join(self._toolsets)}"
            )
        return toolset

    def select(self, toolsets: Mapping[str, Collection[str]]) -> frozenset[str]:
        """Tool names of *toolsets*, each mapped to the methods it leaves out."""
        selected: set[str] = set()
        for reference, disabled_methods in toolsets.items():
            toolset = self.resolve(reference)
            unknown = set(disabled_methods) - set(toolset.tools)
            if unknown:
                raise UnknownToolsetError(
                    f"Toolset '{toolset.namespace}' has no method(s) {', '.join(sorted(unknown))}"
                )
            selected.update(
                tool for method, tool in toolset.tools.items() if method not in disabled_methods
            )
        return frozenset(selected)

    async def list_tools(self) -> list[Tool]:
        tools = await super().list_tools()
        selection = _selected_tools_var.get()
        if selection is None:
            return tools
        return [tool for tool in tools if tool.name in selection]

    async def call_tool(self, name: str, arguments: dict[str, Any], context=None):  # type: ignore[override]
        selection = _selected_tools_var.get()
        if selection is not None and name not in selection:
            raise ToolError(f"Unknown tool: {name}")
        return await super().call_tool(name, arguments, context)

    async def call_tool_result(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        """Call a tool for a caller that is not this server's own transport.

        A failed call comes back as an error result, as it would to a client
        connected to this server, instead of escaping to the caller's dispatcher.
        """
        try:
            result = await self.call_tool(name, arguments)
        except ToolError as exc:
            if isinstance(exc, UnexpectedToolError):
                logger.exception("Tool %r raised an unexpected exception", name)
            return CallToolResult(content=[TextContent(type="text", text=str(exc))], is_error=True)
        if not isinstance(result, CallToolResult):
            raise TypeError(f"Tool {name} returned {type(result).__name__}, not a CallToolResult")
        return result


@contextmanager
def selected_tools(names: frozenset[str] | None) -> Iterator[None]:
    """Serve only *names* for the enclosed requests; None serves every tool."""
    token = _selected_tools_var.set(names)
    try:
        yield
    finally:
        _selected_tools_var.reset(token)


class ToolsetSelectionMiddleware:
    """Narrow a mount to the toolsets its ``?toolsets=`` parameter names.

    ``?toolsets=runs,agents`` (names or namespaces, comma-separated) serves only
    those toolsets; without the parameter the mount serves all of them. A name
    the server does not have is refused with 400 rather than ignored, so a typo
    does not silently hand the harness fewer tools than its owner configured.
    """

    def __init__(self, app: ASGIApp, server: ToolsetMCPServer) -> None:
        self.app = app
        self._server = server

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
        values = query.get(TOOLSETS_QUERY_PARAM)
        if values is None:
            await self.app(scope, receive, send)
            return
        names = [name.strip() for value in values for name in value.split(",") if name.strip()]
        try:
            if not names:
                raise UnknownToolsetError(
                    f"'{TOOLSETS_QUERY_PARAM}' names no toolset. "
                    f"Available: {', '.join(self._server.toolsets)}"
                )
            selection = self._server.select(dict.fromkeys(names, ()))
        except UnknownToolsetError as exc:
            await _send_bad_request(send, str(exc))
            return
        with selected_tools(selection):
            await self.app(scope, receive, send)


async def _send_bad_request(send: Send, message: str) -> None:
    body = json.dumps(
        {"jsonrpc": "2.0", "id": None, "error": {"code": -32602, "message": message}}
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 400,
            "headers": [[b"content-type", b"application/json"]],
        }
    )
    await send({"type": "http.response.body", "body": body})
