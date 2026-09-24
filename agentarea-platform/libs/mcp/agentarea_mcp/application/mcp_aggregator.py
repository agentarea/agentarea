"""Aggregate tools from multiple MCP instances behind one stateless server."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from agentarea_agents_sdk.tools.mcp_app_ui import is_visible_to_model
from mcp.server.mcpserver import MCPServer

from agentarea_mcp.application.mcp_client import (
    connected_mcp_client,
    mcp_verdict_key,
    shared_era_verdict_store,
)
from agentarea_mcp.application.tool_list_cache import ToolListCache
from agentarea_mcp.tool_serialization import serialize_mcp_tool
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
    transport: str | None = None


class MCPAggregatorProxy:
    """Merge tools from multiple MCP instances into one MCPServer."""

    def __init__(
        self,
        name: str,
        description: str,
        members: list[AggregatedMember],
        instance_urls: dict[str, str],
        instance_names: dict[str, str],
        instance_headers: dict[str, dict[str, str]] | None = None,
        tool_cache: ToolListCache | None = None,
        era_verdict_store=None,
    ) -> None:
        self.name = name
        self.description = description
        self.members = sorted(members, key=lambda m: m.order)
        self.instance_urls = instance_urls
        self.instance_names = instance_names
        self.instance_headers = instance_headers or {}
        self._tool_cache = tool_cache
        self._era_verdict_store = (
            era_verdict_store if era_verdict_store is not None else shared_era_verdict_store()
        )
        self._discovery_locks: dict[str, asyncio.Lock] = {}
        self._discovered_ttls: dict[str, int | None] = {}
        self._server: MCPServer | None = None

    @staticmethod
    def _streamable_candidates(url: str, transport: str | None = None) -> list[str]:
        """Return streamable candidates for compatibility with URL-selection callers."""
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

    def _runtime_identity_fields(
        self, member: AggregatedMember, url: str, headers: dict[str, str]
    ) -> dict[str, Any]:
        return {
            "url": url,
            "headers": headers,
            "transport": member.transport,
            "config": member.config,
        }

    def _cache_key(self, member: AggregatedMember, url: str, headers: dict[str, str]) -> str:
        return mcp_verdict_key(
            str(member.mcp_instance_id), self._runtime_identity_fields(member, url, headers)
        )

    async def _discover_member_tools(self, member: AggregatedMember) -> list[dict[str, Any]]:
        """Discover one member's tools, using a fingerprinted short-lived cache."""
        instance_id = str(member.mcp_instance_id)
        mcp_url = self.instance_urls.get(instance_id)
        headers = self.instance_headers.get(instance_id) or {}
        cache_key = self._cache_key(member, mcp_url, headers) if mcp_url else instance_id
        if self._tool_cache is None:
            return await self._discover_member_tools_upstream(member)

        cached = await self._tool_cache.get(cache_key)
        if cached is not None:
            return cached

        lock = self._discovery_locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            cached = await self._tool_cache.get(cache_key)
            if cached is not None:
                return cached

            tools = await self._discover_member_tools_upstream(member)
            ttl_ms = self._discovered_ttls.pop(cache_key, None)
            await self._tool_cache.set(cache_key, tools, ttl_ms=ttl_ms)
            return tools

    async def _discover_member_tools_upstream(
        self, member: AggregatedMember
    ) -> list[dict[str, Any]]:
        instance_id = str(member.mcp_instance_id)
        mcp_url = self.instance_urls.get(instance_id)
        if not mcp_url:
            logger.warning("No URL for member instance %s", instance_id)
            return []
        headers = self.instance_headers.get(instance_id) or {}
        cache_key = self._cache_key(member, mcp_url, headers)
        verdict_key = cache_key
        try:
            async with connected_mcp_client(
                mcp_url,
                headers,
                10.0,
                transport=member.transport,
                verdict_key=verdict_key,
                verdict_store=self._era_verdict_store,
            ) as client:
                result = await client.list_tools()
        except Exception as exc:
            logger.warning(
                "Failed to discover tools from member %s (%s): %s",
                instance_id,
                mcp_url,
                exc,
                exc_info=True,
            )
            return []

        ttl_ms = getattr(result, "ttl_ms", None)
        if ttl_ms == 0 and "ttl_ms" not in getattr(result, "model_fields_set", set()):
            ttl_ms = None
        if ttl_ms is not None and not isinstance(ttl_ms, int):
            ttl_ms = None
        self._discovered_ttls[cache_key] = ttl_ms
        serialized = [serialize_mcp_tool(tool) for tool in result.tools]
        # A bundle proxies tool calls only, not member ui:// resources.
        return [
            {key: value for key, value in tool.items() if key != "_meta"}
            for tool in serialized
            if is_visible_to_model(tool)
        ]

    async def _call_member_tool(
        self, member: AggregatedMember, tool_name: str, arguments: dict[str, Any]
    ) -> Any:
        instance_id = str(member.mcp_instance_id)
        mcp_url = self.instance_urls.get(instance_id)
        if not mcp_url:
            raise ValueError(f"No URL for member instance {instance_id}")
        headers = self.instance_headers.get(instance_id) or {}
        cache_key = self._cache_key(member, mcp_url, headers)
        async with connected_mcp_client(
            mcp_url,
            headers,
            30.0,
            transport=member.transport,
            verdict_key=cache_key,
            verdict_store=self._era_verdict_store,
        ) as client:
            result = await client.call_tool(tool_name, arguments)
        if result.content:
            texts = [
                text
                for block in result.content
                if isinstance((text := getattr(block, "text", None)), str)
            ]
            return "\n".join(texts) if texts else str(result.content)
        if result.structured_content is not None:
            return str(result.structured_content)
        return ""

    def _make_proxy_handler(
        self, member: AggregatedMember, original_name: str, input_schema: dict
    ) -> Callable:
        """Build a handler whose signature mirrors the upstream tool schema."""

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

    async def build_server(self) -> MCPServer:
        server = MCPServer(name=self.name, instructions=self.description)
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
        return self._server.streamable_http_app(streamable_http_path="/", stateless_http=True)

    async def list_namespaced_tools(self) -> list[dict[str, Any]]:
        """Discover every member's tools and return them namespaced."""
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
                    if self._tool_cache is not None:
                        instance_id = str(member.mcp_instance_id)
                        mcp_url = self.instance_urls.get(instance_id)
                        headers = self.instance_headers.get(instance_id) or {}
                        cache_key = (
                            self._cache_key(member, mcp_url, headers) if mcp_url else instance_id
                        )
                        await self._tool_cache.invalidate(cache_key)
                    raise
        raise ValueError(f"No member owns tool {namespaced_name}")
