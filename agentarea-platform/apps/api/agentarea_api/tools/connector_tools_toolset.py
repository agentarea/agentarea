"""ConnectorToolsToolset — find and run the tools of the workspace's connectors.

Two stable tools instead of every connector's tools: the list ``/mcp`` serves
never changes, so a connector connected mid-session is usable at once, and only
the matches of a search carry an ``inputSchema``. A connector is an MCP
connection or an OpenAPI connection; the caller need not know which.
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
from agentarea_common.workspaces.lookup import workspace_slug_for
from agentarea_mcp.application.auth_service import (
    MissingCredentialsError,
    OAuthReauthRequiredError,
)
from agentarea_openapi.application.spec_parser import parse_openapi_operations
from fastapi import HTTPException
from mcp.types import CallToolResult, InputRequiredResult

from ..api.deps.services import get_openapi_connection_service
from ..api.v1 import _catalog_connections, client_mcp
from ..api.v1._catalog_connections import with_existing_connections
from ..api.v1.mcp_oauth_connect import catalog_connect_page_url
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
_METHOD_HINTS = {"DELETE": "destructive", "GET": "read-only", "HEAD": "read-only"}


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


def _openapi_hints(connection: Any) -> dict[str, str | None]:
    """Each operation's safety hint, from its HTTP method: DELETE is destructive, GET reads."""
    if not connection.spec_content:
        return {}
    try:
        operations = parse_openapi_operations(connection.spec_content)
    except ValueError:
        logger.warning("OpenAPI connection %s has an unreadable spec", connection.id, exc_info=True)
        return {}
    return {op["name"]: _METHOD_HINTS.get(op["method"]) for op in operations}


async def _openapi_connections(service: Any) -> list[Any]:
    connections, _total = await service.list_connections(limit=0)
    return connections


async def _openapi_connect_action(
    session: Any, service: Any, user_ctx: Any, connection: Any
) -> dict[str, Any] | None:
    """The link a person opens to sign in to a catalog *connection* again, if it needs one."""
    if connection.registry_item_id is None:
        return None
    if connection.auth_config_id is not None:
        try:
            await service.resolve_headers(connection)
        except (OAuthReauthRequiredError, MissingCredentialsError):
            logger.info(
                "OpenAPI connection %s needs signing in again", connection.id, exc_info=True
            )
        else:
            return None
    slug = user_ctx.workspace_slug or await workspace_slug_for(user_ctx.workspace_id)
    url = catalog_connect_page_url(slug, str(connection.registry_item_id))
    action = {
        "type": "connect",
        "url": url,
        "message": f"Open this link to connect {connection.name}: {url}",
    }
    return with_existing_connections(
        action,
        await _catalog_connections.other_catalog_connections(
            session, user_ctx, connection.registry_item_id, connection.id
        ),
    )


def _unknown_tool(connector_name: str, tool: str, names: list[str]) -> str:
    return json.dumps(
        {
            "error": f"{connector_name} has no tool {tool!r}",
            "suggestions": difflib.get_close_matches(tool, names, n=5),
        }
    )


def _confirmation(connector_name: str, tool: str) -> str:
    return json.dumps(
        {
            "confirmation_required": True,
            "connector": connector_name,
            "tool": tool,
            "message": _CONFIRM_MESSAGE,
        }
    )


def _action_required(connector: Any, action: dict[str, Any]) -> str | InputRequiredResult:
    elicitation = url_elicitation(action["url"], action["message"])
    if elicitation is not None:
        return elicitation
    return json.dumps(
        {
            "connector_id": str(connector.id),
            "connector": connector.name,
            "action_required": action,
        }
    )


def _call_result(connector: Any, tool: str, result: CallToolResult) -> str:
    payload: dict[str, Any] = {
        "connector_id": str(connector.id),
        "connector": connector.name,
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
    """Search and call the tools of the workspace's MCP and OpenAPI connectors."""

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
            openapi_service = await get_openapi_connection_service(repo_factory, secret_mgr)
            readable = await readable_resource_ids(user_ctx.user_id)
            instances = [
                instance
                for instance in await service.list()
                if str(instance.id) in readable
                and _is_verified(instance)
                and (connector is None or _names(instance, connector))
            ]
            connections = [
                connection
                for connection in await _openapi_connections(openapi_service)
                if str(connection.id) in readable
                and connection.status == "active"
                and (connector is None or _names(connection, connector))
            ]
        searched = [(instance, instance.tools or [], _tool_safety_hint) for instance in instances]
        for connection in connections:
            hints = _openapi_hints(connection)
            searched.append(
                (
                    connection,
                    connection.available_tools or [],
                    lambda tool, hints=hints: hints.get(str(tool.get("name"))),
                )
            )
        ranked: list[tuple[int, str, str, dict[str, Any]]] = []
        for owner, tools, hint in searched:
            for tool in tools:
                score = _score(query, query_tokens, tool)
                if score <= 0:
                    continue
                result = {
                    "connector_id": str(owner.id),
                    "connector": owner.name,
                    "tool": tool.get("name"),
                    "description": tool.get("description") or "",
                    "hint": hint(tool),
                    "inputSchema": tool.get("inputSchema") or {"type": "object"},
                }
                ranked.append((score, owner.name.casefold(), str(tool.get("name")), result))
        ranked.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))
        return json.dumps(
            {
                "results": [entry[3] for entry in ranked[:limit]],
                "searched_connectors": len(searched),
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
            openapi_service = await get_openapi_connection_service(repo_factory, secret_mgr)
            instances = [i for i in await service.list() if _names(i, connector)]
            connections = [
                c for c in await _openapi_connections(openapi_service) if _names(c, connector)
            ]
            matches = [*instances, *connections]
            if not matches:
                return json.dumps({"error": f"No connector named {connector!r}"})
            if len(matches) > 1:
                return json.dumps(
                    {
                        "error": f"Connector name {connector!r} is ambiguous; pass one of its ids",
                        "connector_ids": [str(m.id) for m in matches],
                    }
                )
            if connections:
                [connection] = connections
                return await self._call_openapi(
                    session, user_ctx, openapi_service, connection, tool, arguments or {}, confirm
                )
            [instance] = instances
            try:
                await require_permission("use", "mcp_instance", str(instance.id), user_ctx.user_id)
            except HTTPException as exc:
                return json.dumps({"error": exc.detail})

            action = await _connect_action(service, user_ctx, instance, probe=False)
            if action is not None:
                return _action_required(instance, action)

            tools = {t.get("name"): t for t in instance.tools or [] if t.get("name")}
            spec = tools.get(tool)
            if spec is None:
                return _unknown_tool(instance.name, tool, list(tools))
            if _tool_safety_hint(spec) == "destructive" and not confirm:
                return _confirmation(instance.name, tool)

            try:
                result = await client_mcp.call_instance_tool(
                    session, user_ctx, service, instance, tool, arguments or {}
                )
            except Exception as exc:
                logger.error(
                    "tools_call %s on connector %s failed", tool, instance.id, exc_info=True
                )
                return json.dumps({"error": f"Calling {tool} on {instance.name} failed: {exc}"})
        return _call_result(instance, tool, result)

    async def _call_openapi(
        self,
        session: Any,
        user_ctx: Any,
        service: Any,
        connection: Any,
        tool: str,
        arguments: dict[str, Any],
        confirm: bool,
    ) -> str | InputRequiredResult:
        try:
            await require_permission(
                "use", "openapi_connection", str(connection.id), user_ctx.user_id
            )
        except HTTPException as exc:
            return json.dumps({"error": exc.detail})

        action = await _openapi_connect_action(session, service, user_ctx, connection)
        if action is not None:
            return _action_required(connection, action)

        names = [t["name"] for t in connection.available_tools or [] if t.get("name")]
        if tool not in names:
            return _unknown_tool(connection.name, tool, names)
        if _openapi_hints(connection).get(tool) == "destructive" and not confirm:
            return _confirmation(connection.name, tool)

        try:
            result = await client_mcp.call_openapi_tool(
                session, user_ctx, service, connection, tool, arguments
            )
        except Exception as exc:
            logger.error(
                "tools_call %s on OpenAPI connection %s failed", tool, connection.id, exc_info=True
            )
            return json.dumps({"error": f"Calling {tool} on {connection.name} failed: {exc}"})
        return _call_result(connection, tool, result)
