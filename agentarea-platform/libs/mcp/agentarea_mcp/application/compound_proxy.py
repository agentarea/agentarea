"""Compound MCP Proxy — aggregates multiple MCP instances behind a single MCP endpoint.

Creates a FastMCP server that:
1. Connects to each member MCP instance
2. Lists their tools with namespace prefixes
3. Forwards tool calls to the correct member
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import timedelta
from typing import Any
from uuid import UUID

from agentarea_common.config import get_settings
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP

from agentarea_mcp.domain.auth_models import CompoundMCPMember

logger = logging.getLogger(__name__)

# Separator between namespace prefix and tool name
NS_SEP = "__"


class CompoundMCPProxy:
    """Proxy that merges tools from multiple MCP instances into one MCP server."""

    def __init__(
        self,
        name: str,
        description: str,
        routing_mode: str,
        members: list[CompoundMCPMember],
        instance_urls: dict[str, str],
        instance_names: dict[str, str],
    ) -> None:
        self.name = name
        self.description = description
        self.routing_mode = routing_mode
        self.members = sorted(members, key=lambda m: m.order)
        self.instance_urls = instance_urls  # instance_id -> mcp_url
        self.instance_names = instance_names  # instance_id -> display name
        self._server: FastMCP | None = None

    def _get_namespace(self, member: CompoundMCPMember) -> str:
        """Get namespace prefix for a member's tools."""
        prefix = member.config.get("namespace_prefix")
        if prefix:
            return prefix
        # Use instance name (slugified) or first 8 chars of ID
        name = self.instance_names.get(str(member.mcp_instance_id), "")
        if name:
            return name.lower().replace(" ", "_").replace("-", "_")
        return str(member.mcp_instance_id)[:8]

    async def _discover_member_tools(
        self, member: CompoundMCPMember
    ) -> list[dict[str, Any]]:
        """Connect to a member MCP instance and list its tools."""
        instance_id = str(member.mcp_instance_id)
        mcp_url = self.instance_urls.get(instance_id)
        if not mcp_url:
            logger.warning("No URL for member instance %s", instance_id)
            return []

        try:
            async with streamablehttp_client(
                mcp_url, timeout=timedelta(seconds=10)
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return [
                        {
                            "name": t.name,
                            "description": t.description or "",
                            "inputSchema": t.inputSchema if t.inputSchema else {},
                        }
                        for t in result.tools
                    ]
        except Exception:
            logger.exception(
                "Failed to discover tools from member %s (%s)",
                instance_id,
                mcp_url,
            )
            return []

    async def _call_member_tool(
        self, member: CompoundMCPMember, tool_name: str, arguments: dict[str, Any]
    ) -> Any:
        """Forward a tool call to a specific member instance."""
        instance_id = str(member.mcp_instance_id)
        mcp_url = self.instance_urls.get(instance_id)
        if not mcp_url:
            raise ValueError(f"No URL for member instance {instance_id}")

        async with streamablehttp_client(
            mcp_url, timeout=timedelta(seconds=30)
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                # Extract text content from result
                if result.content:
                    texts = []
                    for block in result.content:
                        if hasattr(block, "text"):
                            texts.append(block.text)
                    return "\n".join(texts) if texts else str(result.content)
                return ""

    async def build_server(self) -> FastMCP:
        """Build the FastMCP server with aggregated tools from all members."""
        server = FastMCP(name=self.name, instructions=self.description)

        # Discover tools from all members
        for member in self.members:
            namespace = self._get_namespace(member)
            tools = await self._discover_member_tools(member)

            for tool in tools:
                original_name = tool["name"]
                namespaced_name = f"{namespace}{NS_SEP}{original_name}"
                tool_desc = tool.get("description", "")
                instance_name = self.instance_names.get(
                    str(member.mcp_instance_id), "unknown"
                )
                full_desc = f"[{instance_name}] {tool_desc}"

                # Capture member + original_name in closure
                _member = member
                _original = original_name

                # Register a proxy tool on the server
                @server.tool(
                    name=namespaced_name,
                    description=full_desc,
                )
                async def proxy_tool(
                    _m=_member,
                    _n=_original,
                    **kwargs: Any,
                ) -> str:
                    return await self._call_member_tool(_m, _n, kwargs)

                logger.info(
                    "Registered tool %s -> %s on %s",
                    namespaced_name,
                    original_name,
                    instance_name,
                )

        self._server = server
        return server

    def get_asgi_app(self) -> Any:
        """Get the Starlette/ASGI app for mounting in FastAPI."""
        if not self._server:
            raise RuntimeError("Call build_server() first")
        return self._server.streamable_http_app()

@dataclass
class BundleMember:
    """Lightweight member descriptor for bundle proxies."""

    mcp_instance_id: UUID
    order: int = 0
    config: dict = dataclass_field(default_factory=dict)


async def build_bundle_proxy(
    instance_id: UUID,
    db_session: Any,
    user_context: Any,
) -> CompoundMCPProxy:
    """Build a CompoundMCPProxy from an MCPServerInstance with json_spec.type='bundle'."""
    from agentarea_mcp.infrastructure.auth_repository import MCPServerInstanceRepository

    instance_repo = MCPServerInstanceRepository(db_session, user_context)
    instance = await instance_repo.get_by_id(instance_id)
    if instance is None:
        raise ValueError(f"Instance {instance_id} not found")

    json_spec = instance.json_spec or {}
    if json_spec.get("type") != "bundle":
        raise ValueError(f"Instance {instance_id} is not a bundle type")

    member_ids: list[str] = json_spec.get("members", [])
    if not member_ids:
        raise ValueError(f"Bundle {instance_id} has no members configured")

    gateway_url = get_settings().mcp.MCP_GATEWAY_URL
    instance_urls: dict[str, str] = {}
    instance_names: dict[str, str] = {}
    members: list[BundleMember] = []

    for i, mid in enumerate(member_ids):
        try:
            member_uuid = UUID(mid)
        except ValueError:
            logger.warning("Invalid member ID %s, skipping", mid)
            continue

        member_instance = await instance_repo.get_by_id(member_uuid)
        if not member_instance:
            logger.warning("Bundle member %s not found, skipping", mid)
            continue

        instance_names[mid] = member_instance.name
        member_type = (member_instance.json_spec or {}).get("type", "docker")
        if member_type == "url":
            url = (member_instance.json_spec or {}).get("url", "")
            if url:
                instance_urls[mid] = url
        else:
            instance_urls[mid] = f"{gateway_url}/mcp/{mid}/mcp"

        members.append(BundleMember(mcp_instance_id=member_uuid, order=i))

    if not members:
        raise ValueError(f"Bundle {instance_id} has no resolvable members")

    return CompoundMCPProxy(
        name=instance.name,
        description=instance.description or f"Bundle: {instance.name}",
        routing_mode="parallel",
        members=members,  # type: ignore[arg-type]
        instance_urls=instance_urls,
        instance_names=instance_names,
    )


async def build_compound_proxy(
    compound_id: UUID,
    db_session: Any,
    user_context: Any,
) -> CompoundMCPProxy:
    """Factory: build a CompoundMCPProxy from database records."""
    from agentarea_mcp.application.compound_service import CompoundMCPService
    from agentarea_mcp.infrastructure.auth_repository import (
        CompoundMCPRepository,
        MCPServerInstanceRepository,
    )

    compound_repo = CompoundMCPRepository(db_session, user_context)
    compound_service = CompoundMCPService(compound_repo)

    compound = await compound_service.get(compound_id)
    if compound is None:
        raise ValueError(f"Compound MCP {compound_id} not found")

    members = await compound_service.get_members(compound_id)
    if not members:
        raise ValueError(f"Compound MCP {compound_id} has no members")

    # Resolve MCP URLs for each member instance
    instance_repo = MCPServerInstanceRepository(db_session, user_context)
    gateway_url = get_settings().mcp.MCP_GATEWAY_URL

    instance_urls: dict[str, str] = {}
    instance_names: dict[str, str] = {}

    for member in members:
        iid = str(member.mcp_instance_id)
        instance = await instance_repo.get_by_id(member.mcp_instance_id)
        if not instance:
            logger.warning("Member instance %s not found, skipping", iid)
            continue

        instance_names[iid] = instance.name

        instance_type = (instance.json_spec or {}).get("type", "docker")
        if instance_type == "url":
            url = (instance.json_spec or {}).get("url", "")
            if url:
                instance_urls[iid] = url
        else:
            instance_urls[iid] = f"{gateway_url}/mcp/{iid}/mcp"

    return CompoundMCPProxy(
        name=compound.name,
        description=compound.description or f"Compound MCP: {compound.name}",
        routing_mode=compound.routing_mode,
        members=members,
        instance_urls=instance_urls,
        instance_names=instance_names,
    )
