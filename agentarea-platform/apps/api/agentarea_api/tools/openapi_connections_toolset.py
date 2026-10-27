"""OpenAPIConnectionsToolset — manage OpenAPI-based REST API connections.

Tool method signatures are explicit kwargs (MCP-idiomatic flat wire schema)
but the source of truth for ``create``/``update`` is the Pydantic DTO
``OpenAPIConnectionCreate``/``OpenAPIConnectionUpdate`` in
``agentarea_openapi.schemas.dto``. The contract test in
``tests/unit/test_mcp_rest_parity.py`` enforces parity between toolset
kwargs and DTO fields.
"""

import builtins
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any
from uuid import UUID

from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import requires, unrestricted
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_openapi.schemas.dto import (
    HeaderInput,
    HeaderOutput,
    OpenAPIConnectionCreate,
    OpenAPIConnectionUpdate,
    QueryParamInput,
    QueryParamOutput,
    UrlVariableInput,
)
from pydantic import BaseModel, Field

from .base import platform_context, platform_read_context
from .mcp_servers_toolset import LastDispatchOutput

_CONNECTION_ID = (
    "OpenAPI connection id, from `openapi_connections_list` or `openapi_connections_create`."
)
_AUTH_CONFIG_ID = (
    "UUID of an MCP auth config whose OAuth2 tokens are minted and refreshed for the connection."
)


class OpenAPIConnectionOutput(BaseModel):
    id: str = Field(description="Connection id.")
    name: str = Field(description="Display name.")
    description: str | None = Field(description="Human-readable summary.")
    base_url: str | None = Field(
        description=(
            "Base URL requests are sent to; may hold {name} placeholders. "
            "Null for a connection the platform provides."
        )
    )
    spec_url: str | None = Field(description="URL the OpenAPI spec is fetched from.")
    auth_config_id: str | None = Field(description="Attached OAuth2 auth config, if any.")
    custom_headers: builtins.list[HeaderOutput] = Field(
        description="Headers sent with every request; values are never returned."
    )
    custom_query_params: builtins.list[QueryParamOutput] = Field(
        description="Query parameters sent with every request; values are never returned."
    )
    url_variables: builtins.list[str] = Field(
        description="Names of the base_url placeholders; values are never returned."
    )
    tools_count: int = Field(description="Number of tools discovered from the spec.")
    status: str = Field(description="Connection status; only 'active' connections are callable.")
    last_dispatch: LastDispatchOutput | None = Field(
        description="The last tool call made through the connection."
    )


class OpenAPIConnectionPage(BaseModel):
    items: builtins.list[OpenAPIConnectionOutput] = Field(description="Connections on this page.")
    total: int = Field(description="Connections matching the search across all pages.")


class OpenAPIToolSummary(BaseModel):
    name: str = Field(description="Tool name, callable with `tools_call`.")
    description: str = Field(description="What the operation does.")


class OpenAPIConnectionDetailOutput(OpenAPIConnectionOutput):
    tools: builtins.list[OpenAPIToolSummary] = Field(description="Tools discovered from the spec.")


class DiscoverToolsOutput(BaseModel):
    connection_id: str = Field(description="Connection id.")
    tools_discovered: int = Field(description="Number of tools now stored for the connection.")
    tools: builtins.list[OpenAPIToolSummary] = Field(description="The discovered tools.")


class DeleteOutput(BaseModel):
    deleted: bool = Field(description="True if the connection was deleted; false if not found.")


@contextmanager
def _refusal_reaches_caller() -> Iterator[None]:
    """Give the caller the reason a request was refused, as the REST routes do.

    Any other exception still reaches MCP as an unexpected error, its text kept
    in the server log.
    """
    try:
        yield
    except (ValueError, PermissionError) as exc:
        raise ToolError(str(exc)) from exc


def _serialize(conn: Any) -> dict:
    return {
        "id": str(conn.id),
        "name": conn.name,
        "description": conn.description,
        "base_url": conn.visible_base_url,
        "spec_url": conn.spec_url,
        "auth_config_id": str(conn.auth_config_id) if conn.auth_config_id else None,
        "custom_headers": [
            {"name": h["name"], "secret": h.get("secret", False)}
            for h in (conn.custom_headers or [])
        ],
        "custom_query_params": [
            {"name": p["name"], "secret": p.get("secret", False)}
            for p in (conn.custom_query_params or [])
        ],
        "url_variables": conn.url_variables or [],
        "tools_count": len(conn.available_tools or []),
        "status": conn.status,
        "last_dispatch": conn.last_dispatch,
    }


def _build_service(repo_factory, secret_mgr):
    """Construct an OpenAPIConnectionService bound to the current request context."""
    from agentarea_common.utils.url_safety import OutboundPolicy
    from agentarea_mcp.application.auth_resolver import (
        build_auth_config_access_checker,
        build_owned_auth_releaser,
    )
    from agentarea_openapi.application.service import OpenAPIConnectionService

    return OpenAPIConnectionService(
        repository_factory=repo_factory,
        secret_manager=secret_mgr,
        auth_config_access_checker=build_auth_config_access_checker(repo_factory, secret_mgr),
        owned_auth_releaser=build_owned_auth_releaser(repo_factory, secret_mgr),
        outbound_policy=OutboundPolicy.from_env(),
    )


@toolset(
    namespace="agentarea/openapi_connections",
    display_name="OpenAPI Connections",
    description="Manage OpenAPI connections that expose external APIs as tools.",
    category="platform",
    plane="build",
)
class OpenAPIConnectionsToolset(Toolset):
    """Manage OpenAPI REST API connections: create, list, get, update, discover_tools, delete."""

    open_world = False

    @tool_method(
        display_name="Create OpenAPI connection",
        effect="write",
        open_world=True,
        output=OpenAPIConnectionOutput,
    )
    @unrestricted("any member may add a connection, as POST /v1/openapi-connections allows")
    async def create(
        self,
        name: Annotated[
            str, Field(description="Display name, 1-255 characters, unique per workspace.")
        ],
        base_url: Annotated[
            str,
            Field(
                description="Base URL for API requests, e.g. 'https://api.example.com', at "
                "most 500 characters. The path may hold {name} placeholders filled from "
                "url_variables_json, e.g. 'https://api.telegram.org/bot{token}'."
            ),
        ],
        description: Annotated[
            str | None, Field(description="Optional human-readable summary.")
        ] = None,
        spec_url: Annotated[
            str | None,
            Field(
                description="URL of an OpenAPI 3.x JSON or YAML spec, fetched and parsed now. "
                "Give this or spec_content_json."
            ),
        ] = None,
        spec_content_json: Annotated[
            str,
            Field(
                description="The OpenAPI 3.x spec itself as a JSON object string; use instead "
                "of spec_url when the spec host is unreachable from the platform."
            ),
        ] = "",
        auth_config_id: Annotated[str | None, Field(description=_AUTH_CONFIG_ID)] = None,
        custom_headers_json: Annotated[
            str,
            Field(
                description='JSON array of {"name": "Authorization", "value": "Bearer ..."} '
                "headers sent with every request; non-safe headers are stored encrypted."
            ),
        ] = "",
        custom_query_params_json: Annotated[
            str,
            Field(
                description='JSON array of {"name": "api_key", "value": "...", "secret": true} '
                "query parameters sent with every request; secret (the default) values are "
                "stored encrypted and never returned."
            ),
        ] = "",
        url_variables_json: Annotated[
            str,
            Field(
                description='JSON array of {"name": "token", "value": "..."}, one per {name} '
                "placeholder in base_url; values are stored encrypted and never returned."
            ),
        ] = "",
    ) -> str:
        """Create a new OpenAPI connection.

        Args:
            name: Display name for the connection (unique per workspace).
            base_url: Base URL for API requests, e.g. ``https://api.example.com``.
                The path may hold ``{name}`` placeholders filled from
                ``url_variables_json``, e.g. ``https://api.telegram.org/bot{token}``.
            description: Optional human-readable summary.
            spec_url: URL to an OpenAPI 3.x JSON or YAML spec. Spec is fetched
                and parsed eagerly at create time so the connection is ready.
            spec_content_json: Inline OpenAPI 3.x spec as a JSON-encoded string.
                Use instead of ``spec_url`` when the host is unreachable from
                the API container.
            auth_config_id: Optional MCPAuthConfig UUID for OAuth2 token rotation.
            custom_headers_json: JSON-encoded array of ``{"name", "value"}``
                header objects. Non-safe headers (e.g. Authorization) are stored
                encrypted in the secret manager.
            custom_query_params_json: JSON-encoded array of ``{"name", "value",
                "secret"}`` objects sent in every request's query string, e.g. an
                API key the upstream takes as ``?api_key=``. ``secret`` defaults to
                true: the value is stored encrypted and never returned. A configured
                parameter wins over a same-named one passed at call time.
            url_variables_json: JSON-encoded array of ``{"name", "value"}`` objects,
                one per ``{name}`` placeholder in ``base_url``. Values are stored
                encrypted in the secret manager and never returned.
        """
        spec_content = json.loads(spec_content_json) if spec_content_json else None
        headers_raw = json.loads(custom_headers_json) if custom_headers_json else None
        custom_headers = (
            [HeaderInput.model_validate(h) for h in headers_raw] if headers_raw else None
        )
        query_params_raw = (
            json.loads(custom_query_params_json) if custom_query_params_json else None
        )
        custom_query_params = (
            [QueryParamInput.model_validate(p) for p in query_params_raw]
            if query_params_raw
            else None
        )
        url_variables_raw = json.loads(url_variables_json) if url_variables_json else None
        url_variables = (
            [UrlVariableInput.model_validate(v) for v in url_variables_raw]
            if url_variables_raw
            else None
        )

        payload = OpenAPIConnectionCreate(
            name=name,
            base_url=base_url,
            description=description,
            spec_url=spec_url,
            spec_content=spec_content,
            auth_config_id=UUID(auth_config_id) if auth_config_id else None,
            custom_headers=custom_headers,
            custom_query_params=custom_query_params,
            url_variables=url_variables,
        )

        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            _event_broker,
            secret_mgr,
        ):
            service = _build_service(repo_factory, secret_mgr)
            with _refusal_reaches_caller():
                conn = await service.create_connection(payload)
            return json.dumps(_serialize(conn), default=str)

    @tool_method(
        display_name="List OpenAPI connections", effect="read", output=OpenAPIConnectionPage
    )
    @unrestricted("connections in the caller's workspace, as the REST listing returns them")
    async def list(
        self,
        search: Annotated[
            str,
            Field(
                description="Case-insensitive text to match in names and descriptions; empty for all."
            ),
        ] = "",
        limit: Annotated[int, Field(description="Page size.")] = 100,
        offset: Annotated[int, Field(description="Connections to skip, for paging.")] = 0,
    ) -> str:
        """List OpenAPI connections in the workspace."""
        async with platform_read_context() as (
            _session,
            _user_ctx,
            repo_factory,
            _event_broker,
            secret_mgr,
        ):
            service = _build_service(repo_factory, secret_mgr)
            connections, total = await service.list_connections(
                search=search or None, limit=limit, offset=offset
            )
            return json.dumps(
                {
                    "items": [_serialize(c) for c in connections],
                    "total": total,
                },
                default=str,
            )

    @tool_method(
        display_name="Get OpenAPI connection",
        effect="read",
        output=OpenAPIConnectionDetailOutput,
    )
    @unrestricted("a connection in the caller's workspace, as the REST detail returns it")
    async def get(self, connection_id: Annotated[str, Field(description=_CONNECTION_ID)]) -> str:
        """Get details of an OpenAPI connection, including discovered tools."""
        async with platform_read_context() as (
            _session,
            _user_ctx,
            repo_factory,
            _event_broker,
            secret_mgr,
        ):
            service = _build_service(repo_factory, secret_mgr)
            conn = await service.get_connection(UUID(connection_id))
            if not conn:
                raise ToolError("Connection not found")
            payload = _serialize(conn)
            payload["tools"] = [
                {"name": t["name"], "description": t.get("description", "")}
                for t in (conn.available_tools or [])
            ]
            return json.dumps(payload, default=str)

    @tool_method(
        display_name="Update OpenAPI connection",
        effect="write",
        idempotent=True,
        output=OpenAPIConnectionOutput,
    )
    @requires("edit", "openapi_connection", id_param="connection_id")
    async def update(
        self,
        connection_id: Annotated[str, Field(description=_CONNECTION_ID)],
        name: Annotated[
            str | None, Field(description="New display name, 1-255 characters; omit to keep.")
        ] = None,
        description: Annotated[str | None, Field(description="New summary; omit to keep.")] = None,
        base_url: Annotated[
            str | None,
            Field(description="New base URL, may hold {name} placeholders; omit to keep."),
        ] = None,
        spec_url: Annotated[
            str | None, Field(description="New OpenAPI spec URL; omit to keep.")
        ] = None,
        spec_content_json: Annotated[
            str,
            Field(
                description="Replacement OpenAPI 3.x spec as a JSON object string. Empty keeps it."
            ),
        ] = "",
        auth_config_id: Annotated[
            str | None,
            Field(description=f"{_AUTH_CONFIG_ID} An empty string detaches it; omit to keep."),
        ] = None,
        custom_headers_json: Annotated[
            str,
            Field(
                description='JSON array of {"name", "value"} replacing every header; [] clears '
                "them. Empty keeps them."
            ),
        ] = "",
        custom_query_params_json: Annotated[
            str,
            Field(
                description='JSON array of {"name", "value", "secret"} replacing every query '
                "parameter; [] clears them, an empty value keeps a stored secret. Empty keeps them."
            ),
        ] = "",
        url_variables_json: Annotated[
            str,
            Field(
                description='JSON array of {"name", "value"} replacing every URL variable; must '
                "match the base_url placeholders. Empty keeps them."
            ),
        ] = "",
        cost_json: Annotated[
            str,
            Field(
                description='JSON object with the per-call cost, e.g. {"source": "rate", '
                '"rate": {"amount": "0.01", "currency": "USD"}}; the JSON null restores '
                "the connector's own. Empty keeps it."
            ),
        ] = "",
    ) -> str:
        """Update fields on an existing OpenAPI connection. Only fields explicitly
        set are written. ``custom_headers_json`` replaces the full header set;
        pass ``[]`` to clear all. ``custom_query_params_json`` replaces the full
        ``[{"name", "value", "secret"}]`` query-parameter set the same way; an
        empty value for a secret parameter keeps the stored one. ``url_variables_json`` likewise replaces the
        full ``[{"name", "value"}]`` set, which must match the ``{name}``
        placeholders in ``base_url``. Secret values are stored encrypted in the
        secret manager. Call ``discover_tools`` afterwards to refresh the
        discovered tools list when the spec changes. ``cost_json`` sets what a call
        costs on a connection the workspace pays for, e.g. ``{"source": "rate",
        "rate": {"amount": "0.01", "currency": "USD"}}``; ``null`` restores the
        connector's own.
        """
        patch: dict[str, Any] = {}
        if name is not None:
            patch["name"] = name
        if description is not None:
            patch["description"] = description
        if base_url is not None:
            patch["base_url"] = base_url
        if spec_url is not None:
            patch["spec_url"] = spec_url
        if spec_content_json:
            patch["spec_content"] = json.loads(spec_content_json)
        if auth_config_id is not None:
            patch["auth_config_id"] = UUID(auth_config_id) if auth_config_id else None
        if custom_headers_json:
            raw_headers = json.loads(custom_headers_json)
            patch["custom_headers"] = [HeaderInput.model_validate(h) for h in raw_headers]
        if custom_query_params_json:
            raw_query_params = json.loads(custom_query_params_json)
            patch["custom_query_params"] = [
                QueryParamInput.model_validate(p) for p in raw_query_params
            ]
        if url_variables_json:
            raw_url_variables = json.loads(url_variables_json)
            patch["url_variables"] = [UrlVariableInput.model_validate(v) for v in raw_url_variables]
        if cost_json:
            patch["cost"] = json.loads(cost_json)

        if not patch:
            raise ToolError("no fields to update")

        payload = OpenAPIConnectionUpdate.model_validate(patch)

        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            _event_broker,
            secret_mgr,
        ):
            service = _build_service(repo_factory, secret_mgr)
            with _refusal_reaches_caller():
                conn = await service.update_connection(UUID(connection_id), payload)
            if not conn:
                raise ToolError("Connection not found")
            return json.dumps(_serialize(conn), default=str)

    @tool_method(
        display_name="Discover OpenAPI tools",
        effect="write",
        idempotent=True,
        open_world=True,
        output=DiscoverToolsOutput,
    )
    @requires("edit", "openapi_connection", id_param="connection_id")
    async def discover_tools(
        self, connection_id: Annotated[str, Field(description=_CONNECTION_ID)]
    ) -> str:
        """Re-fetch the OpenAPI spec and refresh the discovered tools list."""
        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            _event_broker,
            secret_mgr,
        ):
            service = _build_service(repo_factory, secret_mgr)
            with _refusal_reaches_caller():
                result = await service.discover_tools(UUID(connection_id))
            return json.dumps(result, default=str)

    @tool_method(
        display_name="Delete OpenAPI connection",
        effect="destructive",
        idempotent=True,
        output=DeleteOutput,
    )
    @requires("delete", "openapi_connection", id_param="connection_id")
    async def delete(self, connection_id: Annotated[str, Field(description=_CONNECTION_ID)]) -> str:
        """Delete an OpenAPI connection, its stored secrets and the OAuth auth config it connected with."""
        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            _event_broker,
            secret_mgr,
        ):
            service = _build_service(repo_factory, secret_mgr)
            deleted = await service.delete_connection(UUID(connection_id))
            return json.dumps({"deleted": deleted})
