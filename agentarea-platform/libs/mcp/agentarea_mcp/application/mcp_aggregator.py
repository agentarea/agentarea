"""Aggregating MCP proxy — merges tools from multiple MCP instances behind one
FastMCP endpoint with ``<namespace>__<tool>`` naming and per-tool forwarding.

Recovered and adapted from the earlier compound-MCP proxy. Decoupled from any
one table: it takes a plain list of members, so it can serve a Client bundle,
a Project bundle, or a standalone compound.
"""

from __future__ import annotations

import asyncio
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

from agentarea_mcp.application.tool_list_cache import ToolListCache
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
    # Transport declared by the instance's spec. Without it every discovery
    # re-probes by URL suffix, and a wrong first candidate costs a full connect
    # timeout — on every tools/list, not once.
    transport: str | None = None


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
        tool_cache: ToolListCache | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.members = sorted(members, key=lambda m: m.order)
        self.instance_urls = instance_urls
        self.instance_names = instance_names
        self.instance_headers = instance_headers or {}
        self._tool_cache = tool_cache
        # Per-member single-flight: harnesses start in bursts, and without this
        # every one of them pays the full round trip on a cold key.
        self._discovery_locks: dict[str, asyncio.Lock] = {}
        self._server: FastMCP | None = None

    @staticmethod
    def _streamable_candidates(url: str, transport: str | None = None) -> list[str]:
        """Ordered streamable-HTTP URLs to try for a member, via the shared resolver.

        Honors the URL as-given first (root-streamable remotes like Vercel), then
        /mcp. The aggregator speaks streamable-HTTP only, so an sse-suffixed member
        URL is best-effort mapped to its /mcp sibling.
        """
        streamable_urls, _ = mcp_transport_candidates(url, transport)
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

    def _candidates_for(self, member: AggregatedMember, url: str) -> list[str]:
        return self._streamable_candidates(url, member.transport)

    async def _discover_member_tools(self, member: AggregatedMember) -> list[dict[str, Any]]:
        """Tools for a member: the upstream's answer, cached briefly.

        The list belongs to the upstream, so it is asked rather than stored;
        the cache only keeps the round trip off the hot path (see
        ``tool_list_cache``). Without a cache configured this is a passthrough.
        """
        instance_id = str(member.mcp_instance_id)
        if self._tool_cache is None:
            return await self._discover_member_tools_upstream(member)

        cached = await self._tool_cache.get(instance_id)
        if cached is not None:
            return cached

        lock = self._discovery_locks.setdefault(instance_id, asyncio.Lock())
        async with lock:
            # A concurrent caller may have filled it while we waited.
            cached = await self._tool_cache.get(instance_id)
            if cached is not None:
                return cached

            tools = await self._discover_member_tools_upstream(member)
            await self._tool_cache.set(instance_id, tools)
            return tools

    async def _discover_member_tools_upstream(
        self, member: AggregatedMember
    ) -> list[dict[str, Any]]:
        instance_id = str(member.mcp_instance_id)
        mcp_url = self.instance_urls.get(instance_id)
        if not mcp_url:
            logger.warning("No URL for member instance %s", instance_id)
            return []
        headers = self.instance_headers.get(instance_id) or None
        last_err: BaseException | None = None
        for candidate in self._candidates_for(member, mcp_url):
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
        candidates = self._candidates_for(member, mcp_url)
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
                            texts = [
                                text
                                for b in result.content
                                if isinstance((text := getattr(b, "text", None)), str)
                            ]
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
        # One network round trip per member, so fan out: serialising them makes
        # a bundle cost the sum of its members, and a harness pays that on every
        # session start. gather keeps the member order of the results.
        discovered = await asyncio.gather(
            *(self._discover_member_tools(member) for member in self.members)
        )

        aggregated: list[dict[str, Any]] = []
        for member, tools in zip(self.members, discovered, strict=True):
            namespace = self._get_namespace(member)
            for tool in tools:
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
                try:
                    return await self._call_member_tool(
                        member, namespaced_name[len(prefix) :], arguments
                    )
                except Exception:
                    # An upstream never announces that its tools changed, so a
                    # failed call is the only evidence we get that the list we
                    # handed out may no longer match it. Drop it and let the
                    # next listing ask again.
                    if self._tool_cache is not None:
                        await self._tool_cache.invalidate(str(member.mcp_instance_id))
                    raise
        raise ValueError(f"No member owns tool {namespaced_name}")
