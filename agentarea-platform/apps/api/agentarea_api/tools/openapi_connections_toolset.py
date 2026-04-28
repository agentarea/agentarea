"""OpenAPIConnectionsToolset — manage OpenAPI-based REST API connections.

Tool method signatures are explicit kwargs (MCP-idiomatic flat wire schema)
but the source of truth for ``create``/``update`` is the Pydantic DTO
``OpenAPIConnectionCreate``/``OpenAPIConnectionUpdate`` in
``agentarea_openapi.schemas.dto``. The contract test in
``tests/unit/test_mcp_rest_parity.py`` enforces parity between toolset
kwargs and DTO fields.
"""

import json
from typing import Any
from uuid import UUID

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_openapi.schemas.dto import (
    HeaderInput,
    OpenAPIConnectionCreate,
    OpenAPIConnectionUpdate,
)

from .base import platform_context, platform_read_context


def _serialize(conn: Any) -> dict:
    return {
        "id": str(conn.id),
        "name": conn.name,
        "description": conn.description,
        "base_url": conn.base_url,
        "spec_url": conn.spec_url,
        "auth_config_id": str(conn.auth_config_id) if conn.auth_config_id else None,
        "custom_headers": [
            {"name": h["name"], "secret": h.get("secret", False)}
            for h in (conn.custom_headers or [])
        ],
        "tools_count": len(conn.available_tools or []),
        "status": conn.status,
    }


def _build_service(repo_factory, secret_mgr):
    """Construct an OpenAPIConnectionService bound to the current request context."""
    from agentarea_common.config import get_settings
    from agentarea_openapi.application.service import OpenAPIConnectionService

    settings = get_settings()
    return OpenAPIConnectionService(
        repository_factory=repo_factory,
        secret_manager=secret_mgr,
        allow_private_urls=settings.mcp.ALLOW_PRIVATE_URLS,
    )


@toolset(
    namespace="agentarea/openapi_connections",
    display_name="OpenAPI Connections",
    description="Manage OpenAPI connections that expose external APIs as tools.",
    category="platform",
)
class OpenAPIConnectionsToolset(Toolset):
    """Manage OpenAPI REST API connections: create, list, get, update, discover_tools, delete."""

    @tool_method
    async def create(
        self,
        name: str,
        base_url: str,
        description: str | None = None,
        spec_url: str | None = None,
        spec_content_json: str = "",
        auth_config_id: str | None = None,
        custom_headers_json: str = "",
    ) -> str:
        """Create a new OpenAPI connection.

        Args:
            name: Display name for the connection (unique per workspace).
            base_url: Base URL for API requests, e.g. ``https://api.example.com``.
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
        """
        spec_content = json.loads(spec_content_json) if spec_content_json else None
        headers_raw = json.loads(custom_headers_json) if custom_headers_json else None
        custom_headers = (
            [HeaderInput.model_validate(h) for h in headers_raw] if headers_raw else None
        )

        payload = OpenAPIConnectionCreate(
            name=name,
            base_url=base_url,
            description=description,
            spec_url=spec_url,
            spec_content=spec_content,
            auth_config_id=UUID(auth_config_id) if auth_config_id else None,
            custom_headers=custom_headers,
        )

        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            _event_broker,
            secret_mgr,
        ):
            service = _build_service(repo_factory, secret_mgr)
            conn = await service.create_connection(payload)
            return json.dumps(_serialize(conn), default=str)

    @tool_method
    async def list(self, search: str = "", limit: int = 100, offset: int = 0) -> str:
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

    @tool_method
    async def get(self, connection_id: str) -> str:
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
                return json.dumps({"error": "Connection not found"})
            payload = _serialize(conn)
            payload["tools"] = [
                {"name": t["name"], "description": t.get("description", "")}
                for t in (conn.available_tools or [])
            ]
            return json.dumps(payload, default=str)

    @tool_method
    async def update(
        self,
        connection_id: str,
        name: str | None = None,
        description: str | None = None,
        base_url: str | None = None,
        spec_url: str | None = None,
        spec_content_json: str = "",
        auth_config_id: str | None = None,
        custom_headers_json: str = "",
    ) -> str:
        """Update fields on an existing OpenAPI connection. Only fields explicitly
        set are written. ``custom_headers_json`` replaces the full header set;
        pass ``[]`` to clear all. Secret values are stored encrypted in the
        secret manager. Call ``discover_tools`` afterwards to refresh the
        discovered tools list when the spec changes.
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

        if not patch:
            return json.dumps({"error": "no fields to update"})

        payload = OpenAPIConnectionUpdate.model_validate(patch)

        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            _event_broker,
            secret_mgr,
        ):
            service = _build_service(repo_factory, secret_mgr)
            conn = await service.update_connection(UUID(connection_id), payload)
            if not conn:
                return json.dumps({"error": "Connection not found"})
            return json.dumps(_serialize(conn), default=str)

    @tool_method
    async def discover_tools(self, connection_id: str) -> str:
        """Re-fetch the OpenAPI spec and refresh the discovered tools list."""
        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            _event_broker,
            secret_mgr,
        ):
            service = _build_service(repo_factory, secret_mgr)
            result = await service.discover_tools(UUID(connection_id))
            return json.dumps(result, default=str)

    @tool_method
    async def delete(self, connection_id: str) -> str:
        """Delete an OpenAPI connection and its stored secret headers."""
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
