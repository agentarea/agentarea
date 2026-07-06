"""Aggregating MCP proxy — merges tools from multiple MCP instances behind one
FastMCP endpoint with ``<namespace>__<tool>`` naming and per-tool forwarding.

Recovered and adapted from the earlier compound-MCP proxy. Decoupled from any
one table: it takes a plain list of members, so it can serve a Client bundle,
a Project bundle, or a standalone compound.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import UUID

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP

from agentarea_mcp.verification import mcp_transport_candidates

logger = logging.getLogger(__name__)

NS_SEP = "__"

_JSON_TO_PY = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


@dataclass
class AggregatedMember:
    """A member MCP instance to aggregate."""

    mcp_instance_id: UUID | str
    order: int = 0
    namespace_prefix: str | None = None
    config: dict = field(default_factory=dict)


class MCPAggregatorProxy:
    """Merges tools from multiple MCP instances into a single FastMCP server."""

    def __init__(
        self,
        name: str,
        description: str,
        members: list[AggregatedMember],
        instance_urls: dict[str, str],
        instance_names: dict[str, str],
        instance_headers: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.members = sorted(members, key=lambda m: m.order)
        self.instance_urls = instance_urls
        self.instance_names = instance_names
        self.instance_headers = instance_headers or {}
        self._server: FastMCP | None = None

    @staticmethod
    def _streamable_candidates(url: str) -> list[str]:
        """Ordered streamable-HTTP URLs to try for a member, via the shared resolver.

        Honors the URL as-given first (root-streamable remotes like Vercel), then
        /mcp. The aggregator speaks streamable-HTTP only, so an sse-suffixed member
        URL is best-effort mapped to its /mcp sibling.
        """
        streamable_urls, _ = mcp_transport_candidates(url)
        if streamable_urls:
            return streamable_urls
        base = url.rstrip("/")
        return [base[:-4] + "/mcp"] if base.endswith("/sse") else [base]

    def _get_namespace(self, member: AggregatedMember) -> str:
        if member.namespace_prefix:
            return member.namespace_prefix
        name = self.instance_names.get(str(member.mcp_instance_id), "")
        if name:
            return name.lower().replace(" ", "_").replace("-", "_")
        return str(member.mcp_instance_id)[:8]

    async def _discover_member_tools(self, member: AggregatedMember) -> list[dict[str, Any]]:
        instance_id = str(member.mcp_instance_id)
        mcp_url = self.instance_urls.get(instance_id)
        if not mcp_url:
            logger.warning("No URL for member instance %s", instance_id)
            return []
        headers = self.instance_headers.get(instance_id) or None
        last_err: BaseException | None = None
        for candidate in self._streamable_candidates(mcp_url):
            try:
                async with streamablehttp_client(
                    candidate, timeout=timedelta(seconds=10), headers=headers
                ) as (
                    read_stream,
                    write_stream,
                    _,
                ):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        result = await session.list_tools()
                        return [
                            {
                                "name": t.name,
                                "description": t.description or "",
                                "inputSchema": t.inputSchema or {},
                            }
                            for t in result.tools
                        ]
            except Exception as e:
                last_err = e
        logger.exception(
            "Failed to discover tools from member %s (%s)",
            instance_id,
            mcp_url,
            exc_info=last_err,
        )
        return []

    async def _call_member_tool(
        self, member: AggregatedMember, tool_name: str, arguments: dict[str, Any]
    ) -> Any:
        instance_id = str(member.mcp_instance_id)
        mcp_url = self.instance_urls.get(instance_id)
        if not mcp_url:
            raise ValueError(f"No URL for member instance {instance_id}")
        headers = self.instance_headers.get(instance_id) or None
        candidates = self._streamable_candidates(mcp_url)
        last_err: BaseException | None = None
        for idx, candidate in enumerate(candidates):
            try:
                async with streamablehttp_client(
                    candidate, timeout=timedelta(seconds=30), headers=headers
                ) as (
                    read_stream,
                    write_stream,
                    _,
                ):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        result = await session.call_tool(tool_name, arguments)
                        if result.content:
                            texts = [b.text for b in result.content if hasattr(b, "text")]
                            return "\n".join(texts) if texts else str(result.content)
                        return ""
            except Exception as e:
                last_err = e
                if idx == len(candidates) - 1:
                    raise
        raise last_err or ValueError(f"No usable MCP transport for {mcp_url}")

    def _make_proxy_handler(
        self, member: AggregatedMember, original_name: str, input_schema: dict
    ) -> Callable:
        """Build a handler whose signature mirrors the upstream tool's inputSchema,
        so FastMCP advertises the real parameters to the connecting harness.
        """

        async def handler(_m=member, _n=original_name, **kwargs: Any) -> str:
            return await self._call_member_tool(_m, _n, kwargs)

        properties = (input_schema or {}).get("properties", {})
        required = set((input_schema or {}).get("required", []))
        params = []
        annotations: dict[str, Any] = {"return": str}
        for param_name, param_info in properties.items():
            py_type = _JSON_TO_PY.get(param_info.get("type", "string"), str)
            annotations[param_name] = py_type
            params.append(
                inspect.Parameter(
                    param_name,
                    inspect.Parameter.KEYWORD_ONLY,
                    default=inspect.Parameter.empty if param_name in required else None,
                    annotation=py_type,
                )
            )
        handler.__signature__ = inspect.Signature(params)
        handler.__annotations__ = annotations
        return handler

    async def build_server(self) -> FastMCP:
        server = FastMCP(
            name=self.name,
            instructions=self.description,
            streamable_http_path="/",
            stateless_http=True,
        )
        for member in self.members:
            namespace = self._get_namespace(member)
            tools = await self._discover_member_tools(member)
            instance_name = self.instance_names.get(str(member.mcp_instance_id), "unknown")
            for tool in tools:
                namespaced_name = f"{namespace}{NS_SEP}{tool['name']}"
                handler = self._make_proxy_handler(
                    member, tool["name"], tool.get("inputSchema", {})
                )
                server.add_tool(
                    handler,
                    name=namespaced_name,
                    description=f"[{instance_name}] {tool.get('description', '')}",
                )
        self._server = server
        return server

    def get_asgi_app(self) -> Any:
        if not self._server:
            raise RuntimeError("Call build_server() first")
        return self._server.streamable_http_app()

    async def list_namespaced_tools(self) -> list[dict[str, Any]]:
        """Discover every member's tools and return them namespaced.

        Used by the dynamically-scoped client endpoint, which drives the MCP
        protocol itself instead of minting a standalone FastMCP server.
        """
        aggregated: list[dict[str, Any]] = []
        for member in self.members:
            namespace = self._get_namespace(member)
            for tool in await self._discover_member_tools(member):
                aggregated.append(
                    {
                        "name": f"{namespace}{NS_SEP}{tool['name']}",
                        "description": tool.get("description", ""),
                        "inputSchema": tool.get("inputSchema") or {"type": "object"},
                    }
                )
        return aggregated

    async def call_namespaced_tool(self, namespaced_name: str, arguments: dict[str, Any]) -> Any:
        """Route a namespaced tool call to the owning member instance."""
        for member in self.members:
            namespace = self._get_namespace(member)
            prefix = f"{namespace}{NS_SEP}"
            if namespaced_name.startswith(prefix):
                return await self._call_member_tool(
                    member, namespaced_name[len(prefix) :], arguments
                )
        raise ValueError(f"No member owns tool {namespaced_name}")
