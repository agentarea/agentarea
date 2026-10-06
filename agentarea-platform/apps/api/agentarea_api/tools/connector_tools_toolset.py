"""ConnectorToolsToolset — find and run the tools of the workspace's connectors.

Two stable tools instead of every connector's tools: the list ``/mcp`` serves
never changes, so a connector connected mid-session is usable at once, and only
the matches of a search carry an ``inputSchema``.
"""

import difflib
import json
import logging
import re
from typing import Any

from agentarea_agents_sdk.mcp_server.elicitation import url_elicitation
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import enforced_in_handler
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.auth.permission import require_permission
from agentarea_common.auth.resource_visibility import readable_resource_ids
from fastapi import HTTPException
from mcp.types import InputRequiredResult

from ..api.v1 import client_mcp
from .base import platform_context, platform_read_context
from .mcp_servers_toolset import _connect_action, _tool_safety_hint

logger = logging.getLogger(__name__)

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")
_EXACT_NAME = 100
_NAME_TOKEN = 3
_NAME_PREFIX = 2
_DESCRIPTION_TOKEN = 1
_CONFIRM_MESSAGE = (
    "This tool is marked destructive. Ask the user to confirm, then call again with confirm=true."
)


def _tokens(text: str) -> set[str]:
    return {token for token in _TOKEN_SPLIT.split(text.lower()) if token}


def _score(query: str, query_tokens: set[str], tool: dict[str, Any]) -> int:
    name = str(tool.get("name") or "")
    name_tokens = _tokens(name)
    annotations = tool.get("annotations") or {}
    description_tokens = _tokens(
        f"{tool.get('description') or ''} {annotations.get('title') or ''}"
    )
    score = _EXACT_NAME if query.strip().lower() == name.lower() else 0
    for token in query_tokens:
        if token in name_tokens:
            score += _NAME_TOKEN
        elif len(token) >= 3 and any(n.startswith(token) for n in name_tokens):
            score += _NAME_PREFIX
        elif token in description_tokens:
            score += _DESCRIPTION_TOKEN
    return score


def _is_verified(instance: Any) -> bool:
    return (instance.verification or {}).get("status") == "succeeded"


def _names(instance: Any, connector: str) -> bool:
    return connector == str(instance.id) or connector.casefold() == instance.name.casefold()


def _instance_service(repo_factory: Any, event_broker: Any, secret_mgr: Any) -> Any:
    from agentarea_mcp.application.service import MCPServerInstanceService

    return MCPServerInstanceService(
        repository_factory=repo_factory,
        event_broker=event_broker,
        secret_manager=secret_mgr,
    )


@toolset(
    namespace="agentarea/tools",
    display_name="Connector Tools",
    description="Search the tools of the workspace's connectors and call them.",
    category="platform",
    plane="operate",
    register=False,
)
class ConnectorToolsToolset(Toolset):
    """Search and call the tools of the workspace's MCP connectors."""

    @property
    def name(self) -> str:
        return "tools"

    @tool_method(effect="read")
    @enforced_in_handler(
        "searches only the workspace's connectors the graph says the caller may read"
    )
    async def search(self, query: str, connector: str | None = None, limit: int = 8) -> str:
        """Find tools across the workspace's connected connectors.

        Matches tool names and descriptions; only the matches carry their
        ``inputSchema``. Run one with ``tools_call``.

        Args:
            query: Words describing what the tool should do, or a tool name.
            connector: Search only this connector (its id or name).
            limit: Most matches to return, 1..50.
        """
        if not 1 <= limit <= 50:
            return json.dumps({"error": f"limit must be between 1 and 50, got {limit}"})
        query_tokens = _tokens(query)
        async with platform_read_context() as (
            _session,
            user_ctx,
            repo_factory,
            event_broker,
            secret_mgr,
        ):
            service = _instance_service(repo_factory, event_broker, secret_mgr)
            readable = await readable_resource_ids(user_ctx.user_id)
            instances = [
                instance
                for instance in await service.list()
                if str(instance.id) in readable
                and _is_verified(instance)
                and (connector is None or _names(instance, connector))
            ]
        ranked: list[tuple[int, str, str, dict[str, Any]]] = []
        for instance in instances:
            for tool in instance.tools or []:
                score = _score(query, query_tokens, tool)
                if score <= 0:
                    continue
                result = {
                    "connector_id": str(instance.id),
                    "connector": instance.name,
                    "tool": tool.get("name"),
                    "description": tool.get("description") or "",
                    "hint": _tool_safety_hint(tool),
                    "inputSchema": tool.get("inputSchema") or {"type": "object"},
                }
                ranked.append((score, instance.name.casefold(), str(tool.get("name")), result))
        ranked.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))
        return json.dumps(
            {
                "results": [entry[3] for entry in ranked[:limit]],
                "searched_connectors": len(instances),
            },
            default=str,
        )

    @tool_method(effect="write")
    @enforced_in_handler(
        "resolves the connector first, then demands use on it; the workspace policy "
        "judges the call in the client dispatch"
    )
    async def call(
        self,
        connector: str,
        tool: str,
        arguments: dict[str, Any] | None = None,
        confirm: bool = False,
    ) -> str | InputRequiredResult:
        """Run a tool of a workspace connector, as found by ``tools_search``.

        A tool marked destructive is not run until the user confirms: ask them,
        then call again with ``confirm=true``. A connector still waiting on a
        sign-in or key answers with the link the user opens to connect it.

        Args:
            connector: The connector's id or name.
            tool: The tool's name, exactly as ``tools_search`` returned it.
            arguments: The tool's arguments, matching its ``inputSchema``.
            confirm: True once the user confirmed running a destructive tool.
        """
        async with platform_context() as (
            session,
            user_ctx,
            repo_factory,
            event_broker,
            secret_mgr,
        ):
            service = _instance_service(repo_factory, event_broker, secret_mgr)
            matches = [i for i in await service.list() if _names(i, connector)]
            if not matches:
                return json.dumps({"error": f"No connector named {connector!r}"})
            if len(matches) > 1:
                return json.dumps(
                    {
                        "error": f"Connector name {connector!r} is ambiguous; pass one of its ids",
                        "connector_ids": [str(i.id) for i in matches],
                    }
                )
            [instance] = matches
            try:
                await require_permission("use", "mcp_instance", str(instance.id), user_ctx.user_id)
            except HTTPException as exc:
                return json.dumps({"error": exc.detail})

            action = await _connect_action(service, user_ctx, instance, probe=False)
            if action is not None:
                elicitation = url_elicitation(action["url"], action["message"])
                if elicitation is not None:
                    return elicitation
                return json.dumps(
                    {
                        "connector_id": str(instance.id),
                        "connector": instance.name,
                        "action_required": action,
                    }
                )

            tools = {t.get("name"): t for t in instance.tools or [] if t.get("name")}
            spec = tools.get(tool)
            if spec is None:
                return json.dumps(
                    {
                        "error": f"{instance.name} has no tool {tool!r}",
                        "suggestions": difflib.get_close_matches(tool, list(tools), n=5),
                    }
                )
            if _tool_safety_hint(spec) == "destructive" and not confirm:
                return json.dumps(
                    {
                        "confirmation_required": True,
                        "connector": instance.name,
                        "tool": tool,
                        "message": _CONFIRM_MESSAGE,
                    }
                )

            try:
                result = await client_mcp.call_instance_tool(
                    session, user_ctx, service, instance, tool, arguments or {}
                )
            except Exception as exc:
                logger.error(
                    "tools_call %s on connector %s failed", tool, instance.id, exc_info=True
                )
                return json.dumps({"error": f"Calling {tool} on {instance.name} failed: {exc}"})

        payload: dict[str, Any] = {
            "connector_id": str(instance.id),
            "connector": instance.name,
            "tool": tool,
            "content": [
                block.model_dump(mode="json", by_alias=True, exclude_none=True)
                for block in result.content
            ],
        }
        if result.structured_content is not None:
            payload["structuredContent"] = result.structured_content
        if result.is_error:
            payload["is_error"] = True
        return json.dumps(payload, default=str)
