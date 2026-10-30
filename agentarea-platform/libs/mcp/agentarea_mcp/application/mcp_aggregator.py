"""Aggregate tools from multiple MCP instances behind one stateless server."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, TypeVar
from uuid import UUID

from agentarea_agents_sdk.tools.mcp_app_ui import (
    is_callable_from_app,
    is_visible_to_model,
    opens_app,
    tool_ui_resource_uri,
)
from agentarea_agents_sdk.tools.mcp_tool_identity import server_label
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, ReadResourceResult, Resource

from agentarea_mcp.application.mcp_client import (
    ConnectedMCPClient,
    connected_mcp_client,
    mcp_verdict_key,
    pinned_client_factory,
    platform_client_factory,
    shared_era_verdict_store,
)
from agentarea_mcp.application.tool_list_cache import ToolListCache
from agentarea_mcp.dispatch_stamps import record_dispatch
from agentarea_mcp.tool_serialization import serialize_mcp_tool
from agentarea_mcp.verification import mcp_transport_candidates

logger = logging.getLogger(__name__)

NS_SEP = "__"
UI_SCHEME = "ui://"

_T = TypeVar("_T")

_JSON_TO_PY = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def namespaced_resource_uri(namespace: str, uri: str) -> str | None:
    """``ui://{namespace}/{rest}`` for a member's ``ui://{rest}``; None for any other scheme."""
    if not uri.startswith(UI_SCHEME):
        return None
    return f"{UI_SCHEME}{namespace}/{uri[len(UI_SCHEME) :]}"


def _listed(name: str, tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "description": tool.get("description", ""),
        "inputSchema": tool.get("inputSchema") or {"type": "object"},
    }


def _error_text(result: CallToolResult) -> str:
    texts = [
        text for block in result.content if isinstance((text := getattr(block, "text", None)), str)
    ]
    return "\n".join(texts) or "MCP tool returned error"


@dataclass
class AggregatedMember:
    """A member MCP instance to aggregate."""

    mcp_instance_id: UUID | str
    order: int = 0
    namespace_prefix: str | None = None
    config: dict = field(default_factory=dict)
    transport: str | None = None
    # A member-supplied URL is dialed only at vetted addresses; only the
    # platform's own gateway URL may opt out.
    pinned: bool = True
    # The member's tools the aggregate serves; None serves all of them.
    allowed_tools: frozenset[str] | None = None

    def serves(self, tool_name: str) -> bool:
        return self.allowed_tools is None or tool_name in self.allowed_tools


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
        # The app-only tools of each member whose app the aggregate carries, as
        # last discovered in the app view; owner_of serves them beside allowed_tools.
        self._app_only: dict[str, frozenset[str]] = {}
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
        if name and not name.isascii():
            # Tool names must be ASCII; an ASCII name keeps its namespace as before.
            return server_label(name)
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

    @staticmethod
    def _client_factory(member: AggregatedMember) -> Callable[..., Any]:
        return pinned_client_factory() if member.pinned else platform_client_factory

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
                httpx_client_factory=self._client_factory(member),
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
        return [serialize_mcp_tool(tool) for tool in result.tools]

    @staticmethod
    def _model_view(member: AggregatedMember, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The tools an agent sees: the model-visible ones the member serves, without ``_meta``."""
        return [
            {key: value for key, value in tool.items() if key != "_meta"}
            for tool in tools
            if is_visible_to_model(tool) and member.serves(tool["name"])
        ]

    def _note_app(self, member: AggregatedMember, tools: list[dict[str, Any]]) -> frozenset[str]:
        """Record whether the aggregate carries *member*'s app; the app's app-only tools.

        The app is carried once a model-visible tool the member serves opens it.
        Its app-only tools are the ones the app calls, so they follow the app
        rather than ``allowed_tools``.
        """
        instance_id = str(member.mcp_instance_id)
        if not any(opens_app(tool) and member.serves(tool["name"]) for tool in tools):
            self._app_only.pop(instance_id, None)
            return frozenset()
        app_only = frozenset(
            tool["name"]
            for tool in tools
            if not is_visible_to_model(tool) and is_callable_from_app(tool)
        )
        self._app_only[instance_id] = app_only
        return app_only

    def _app_view(
        self, member: AggregatedMember, tools: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """The tools a host that renders apps sees: the model's, plus carried apps' app-only tools."""
        app_only = self._note_app(member, tools)
        return [
            tool
            for tool in tools
            if (is_visible_to_model(tool) and member.serves(tool["name"]))
            or tool["name"] in app_only
        ]

    def _serves(self, member: AggregatedMember, tool_name: str) -> bool:
        return member.serves(tool_name) or tool_name in self._app_only.get(
            str(member.mcp_instance_id), frozenset()
        )

    @asynccontextmanager
    async def _dial(
        self, member: AggregatedMember, timeout: float
    ) -> AsyncIterator[ConnectedMCPClient]:
        instance_id = str(member.mcp_instance_id)
        mcp_url = self.instance_urls.get(instance_id)
        if not mcp_url:
            raise ValueError(f"No URL for member instance {instance_id}")
        headers = self.instance_headers.get(instance_id) or {}
        async with connected_mcp_client(
            mcp_url,
            headers,
            timeout,
            transport=member.transport,
            verdict_key=self._cache_key(member, mcp_url, headers),
            verdict_store=self._era_verdict_store,
            httpx_client_factory=self._client_factory(member),
        ) as client:
            yield client

    async def _call_member_tool_result(
        self, member: AggregatedMember, tool_name: str, arguments: dict[str, Any]
    ) -> CallToolResult:
        instance_id = str(member.mcp_instance_id)
        mcp_url = self.instance_urls.get(instance_id)
        if not mcp_url:
            raise ValueError(f"No URL for member instance {instance_id}")
        headers = self.instance_headers.get(instance_id) or {}
        cache_key = self._cache_key(member, mcp_url, headers)
        try:
            async with connected_mcp_client(
                mcp_url,
                headers,
                30.0,
                transport=member.transport,
                verdict_key=cache_key,
                verdict_store=self._era_verdict_store,
                httpx_client_factory=self._client_factory(member),
            ) as client:
                result = await client.call_tool(tool_name, arguments)
        except Exception as exc:
            record_dispatch(member.mcp_instance_id, error=str(exc) or type(exc).__name__)
            raise
        record_dispatch(
            member.mcp_instance_id,
            error=_error_text(result) if result.is_error else None,
        )
        return result

    async def _call_member_tool(
        self, member: AggregatedMember, tool_name: str, arguments: dict[str, Any]
    ) -> Any:
        result = await self._call_member_tool_result(member, tool_name, arguments)
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
            tools = self._model_view(member, await self._discover_member_tools(member))
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

    async def _discover_all(self) -> list[list[dict[str, Any]]]:
        return await asyncio.gather(
            *(self._discover_member_tools(member) for member in self.members)
        )

    async def list_namespaced_tools(self) -> list[dict[str, Any]]:
        """Discover every member's tools and return the model's view of them, namespaced."""
        discovered = await self._discover_all()
        return [
            _listed(self.qualified_name(member, tool["name"]), tool)
            for member, tools in zip(self.members, discovered, strict=True)
            for tool in self._model_view(member, tools)
        ]

    async def _app_tools(self) -> list[tuple[AggregatedMember, dict[str, Any]]]:
        discovered = await self._discover_all()
        return [
            (member, tool)
            for member, tools in zip(self.members, discovered, strict=True)
            for tool in self._app_view(member, tools)
        ]

    async def list_app_tools(self) -> list[dict[str, Any]]:
        """The app view of every member's tools, namespaced.

        Each tool keeps its ``_meta.ui``, its ``ui://`` resource URI namespaced
        so ``read_app_resource`` can route it back.
        """
        listed: list[dict[str, Any]] = []
        for member, tool in await self._app_tools():
            entry = _listed(self.qualified_name(member, tool["name"]), tool)
            ui = dict((tool.get("_meta") or {}).get("ui") or {})
            ui.pop("resourceUri", None)
            if (uri := tool_ui_resource_uri(tool)) is not None:
                ui["resourceUri"] = namespaced_resource_uri(self._get_namespace(member), uri)
            if ui:
                entry["_meta"] = {"ui": ui}
            listed.append(entry)
        return listed

    async def resolve_tool(self, name: str) -> str:
        """The namespaced name a call of ``name`` runs.

        ``name`` itself when a member serves it; otherwise, as an app calls its
        own tools, the one served tool whose raw name it is. Raises ValueError
        when no served tool, or more than one, answers to it.
        """
        if self.owner_of(name) is not None:
            return name
        served = await self._app_tools()
        if self.owner_of(name) is not None:
            return name
        matches = sorted(
            self.qualified_name(member, tool["name"])
            for member, tool in served
            if tool["name"] == name
        )
        if len(matches) > 1:
            raise ValueError(
                f"Tool {name} is served by more than one connection; call one of {', '.join(matches)}"
            )
        if not matches:
            raise ValueError(f"No member owns tool {name}")
        return matches[0]

    def owner_of(self, namespaced_name: str) -> tuple[AggregatedMember, str] | None:
        """The member serving ``namespaced_name`` and the raw name it advertises.

        None when no member's namespace claims the name, or the claiming member
        does not serve that tool.
        """
        for member in self.members:
            prefix = f"{self._get_namespace(member)}{NS_SEP}"
            if namespaced_name.startswith(prefix):
                tool_name = namespaced_name[len(prefix) :]
                return (member, tool_name) if self._serves(member, tool_name) else None
        return None

    def resource_owner(self, uri: str) -> tuple[AggregatedMember, str] | None:
        """The member a namespaced ``ui://`` URI belongs to, and the URI it serves it under."""
        for member in self.members:
            prefix = f"{UI_SCHEME}{self._get_namespace(member)}/"
            if uri.startswith(prefix):
                return member, f"{UI_SCHEME}{uri[len(prefix) :]}"
        return None

    async def list_app_resources(self) -> list[Resource]:
        """The ``ui://`` resources of every app the aggregate carries, namespaced."""
        await self._app_tools()
        with_apps = [m for m in self.members if str(m.mcp_instance_id) in self._app_only]
        listed = await asyncio.gather(*(self._member_resources(m) for m in with_apps))
        return [
            resource.model_copy(update={"uri": uri})
            for member, resources in zip(with_apps, listed, strict=True)
            for resource in resources
            if (uri := namespaced_resource_uri(self._get_namespace(member), resource.uri))
        ]

    async def _member_resources(self, member: AggregatedMember) -> list[Resource]:
        try:
            async with self._dial(member, 10.0) as client:
                return (await client.list_resources()).resources
        except Exception as exc:
            logger.warning(
                "Failed to list resources of member %s: %s",
                member.mcp_instance_id,
                exc,
                exc_info=True,
            )
            return []

    async def read_app_resource(self, uri: str) -> ReadResourceResult | None:
        """Read a namespaced ``ui://`` resource from its member; None when no carried app owns it."""
        owner = self.resource_owner(uri)
        if owner is None:
            return None
        member, member_uri = owner
        self._note_app(member, await self._discover_member_tools(member))
        if str(member.mcp_instance_id) not in self._app_only:
            return None
        async with self._dial(member, 30.0) as client:
            result = await client.read_resource(member_uri)
        namespace = self._get_namespace(member)
        return result.model_copy(
            update={
                "contents": [
                    content.model_copy(
                        update={
                            "uri": namespaced_resource_uri(namespace, content.uri) or content.uri
                        }
                    )
                    for content in result.contents
                ]
            }
        )

    def qualified_name(self, member: AggregatedMember, tool_name: str) -> str:
        """The name the aggregate serves *member*'s ``tool_name`` under."""
        return f"{self._get_namespace(member)}{NS_SEP}{tool_name}"

    async def call_namespaced_tool(self, namespaced_name: str, arguments: dict[str, Any]) -> Any:
        """Route a namespaced tool call to the owning member instance."""
        return await self._route_call(namespaced_name, arguments, self._call_member_tool)

    async def call_namespaced_tool_result(
        self, namespaced_name: str, arguments: dict[str, Any]
    ) -> CallToolResult:
        """Route a namespaced tool call and return the member's result unflattened."""
        return await self._route_call(namespaced_name, arguments, self._call_member_tool_result)

    async def _route_call(
        self,
        namespaced_name: str,
        arguments: dict[str, Any],
        call: Callable[[AggregatedMember, str, dict[str, Any]], Awaitable[_T]],
    ) -> _T:
        owner = self.owner_of(namespaced_name)
        if owner is None:
            raise ValueError(f"No member owns tool {namespaced_name}")
        member, tool_name = owner
        try:
            return await call(member, tool_name, arguments)
        except Exception:
            if self._tool_cache is not None:
                instance_id = str(member.mcp_instance_id)
                mcp_url = self.instance_urls.get(instance_id)
                headers = self.instance_headers.get(instance_id) or {}
                cache_key = self._cache_key(member, mcp_url, headers) if mcp_url else instance_id
                await self._tool_cache.invalidate(cache_key)
            raise
