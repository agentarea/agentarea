"""OpenAPIConnectionsToolset — manage OpenAPI-based REST API connections."""

import json
from typing import Any
from uuid import UUID

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method

from .base import platform_context


def _serialize(conn: Any, secret_mgr_resolved_headers: dict[str, str] | None = None) -> dict:
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


class OpenAPIConnectionsToolset(Toolset):
    """Manage OpenAPI REST API connections: create, list, get, discover tools."""

    @property
    def name(self) -> str:
        return "openapi_connections"

    @tool_method
    async def create(
        self,
        name: str,
        base_url: str,
        spec_url: str = "",
        spec_content_json: str = "",
        description: str = "",
        custom_headers_json: str = "",
        auth_config_id: str = "",
    ) -> str:
        """Create a new OpenAPI connection.

        Args:
            name: Display name for the connection.
            base_url: Base URL for API requests (e.g. https://api.example.com).
            spec_url: URL to the OpenAPI/Swagger JSON spec. Spec is fetched + parsed eagerly.
            spec_content_json: Inline JSON spec (alternative to spec_url, useful when the
                spec host is unreachable from the API container).
            description: Optional description.
            custom_headers_json: JSON array of {"name", "value"} headers. Non-safe headers
                (e.g. Authorization) are stored encrypted in the secret manager.
            auth_config_id: Optional MCPAuthConfig UUID for OAuth2 token rotation.
        """
        from agentarea_common.config import get_settings
        from agentarea_openapi.application.service import OpenAPIConnectionService

        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            _event_broker,
            secret_mgr,
        ):
            settings = get_settings()
            service = OpenAPIConnectionService(
                repository_factory=repo_factory,
                secret_manager=secret_mgr,
                allow_private_urls=settings.mcp.ALLOW_PRIVATE_URLS,
            )

            headers = json.loads(custom_headers_json) if custom_headers_json else None
            spec_content = json.loads(spec_content_json) if spec_content_json else None

            conn = await service.create_connection(
                name=name,
                base_url=base_url,
                description=description or None,
                spec_url=spec_url or None,
                spec_content=spec_content,
                auth_config_id=UUID(auth_config_id) if auth_config_id else None,
                custom_headers=headers,
            )
            return json.dumps(_serialize(conn), default=str)

    @tool_method
    async def list(self, search: str = "", limit: int = 100, offset: int = 0) -> str:
        """List OpenAPI connections in the workspace."""
        from agentarea_common.config import get_settings
        from agentarea_openapi.application.service import OpenAPIConnectionService

        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            _event_broker,
            secret_mgr,
        ):
            settings = get_settings()
            service = OpenAPIConnectionService(
                repository_factory=repo_factory,
                secret_manager=secret_mgr,
                allow_private_urls=settings.mcp.ALLOW_PRIVATE_URLS,
            )
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
        from agentarea_common.config import get_settings
        from agentarea_openapi.application.service import OpenAPIConnectionService

        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            _event_broker,
            secret_mgr,
        ):
            settings = get_settings()
            service = OpenAPIConnectionService(
                repository_factory=repo_factory,
                secret_manager=secret_mgr,
                allow_private_urls=settings.mcp.ALLOW_PRIVATE_URLS,
            )
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
        name: str = "",
        description: str = "",
        base_url: str = "",
        spec_url: str = "",
        spec_content_json: str = "",
        custom_headers_json: str = "",
    ) -> str:
        """Update fields on an existing OpenAPI connection.

        Only non-empty fields are applied. custom_headers_json replaces the full
        header set; pass [] to clear all. Secret header values (e.g. Authorization)
        are stored encrypted in the secret manager. To refresh the discovered tools
        after changing spec_url/spec_content, call discover_tools afterwards.
        """
        from agentarea_common.config import get_settings
        from agentarea_openapi.application.service import OpenAPIConnectionService

        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            _event_broker,
            secret_mgr,
        ):
            settings = get_settings()
            service = OpenAPIConnectionService(
                repository_factory=repo_factory,
                secret_manager=secret_mgr,
                allow_private_urls=settings.mcp.ALLOW_PRIVATE_URLS,
            )
            uid = UUID(connection_id)

            if custom_headers_json:
                headers = json.loads(custom_headers_json)
                conn = await service.update_headers(uid, headers)
                if not conn:
                    return json.dumps({"error": "Connection not found"})

            fields: dict[str, Any] = {}
            if name:
                fields["name"] = name
            if description:
                fields["description"] = description
            if base_url:
                fields["base_url"] = base_url
            if spec_url:
                fields["spec_url"] = spec_url
            if spec_content_json:
                fields["spec_content"] = json.loads(spec_content_json)

            if fields:
                conn = await service.update_connection(uid, **fields)
            elif not custom_headers_json:
                return json.dumps({"error": "no fields to update"})

            if not conn:
                return json.dumps({"error": "Connection not found"})
            return json.dumps(_serialize(conn), default=str)

    @tool_method
    async def discover_tools(self, connection_id: str) -> str:
        """Re-fetch the OpenAPI spec and refresh the discovered tools list."""
        from agentarea_common.config import get_settings
        from agentarea_openapi.application.service import OpenAPIConnectionService

        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            _event_broker,
            secret_mgr,
        ):
            settings = get_settings()
            service = OpenAPIConnectionService(
                repository_factory=repo_factory,
                secret_manager=secret_mgr,
                allow_private_urls=settings.mcp.ALLOW_PRIVATE_URLS,
            )
            result = await service.discover_tools(UUID(connection_id))
            return json.dumps(result, default=str)

    @tool_method
    async def delete(self, connection_id: str) -> str:
        """Delete an OpenAPI connection and its stored secret headers."""
        from agentarea_common.config import get_settings
        from agentarea_openapi.application.service import OpenAPIConnectionService

        async with platform_context() as (
            _session,
            _user_ctx,
            repo_factory,
            _event_broker,
            secret_mgr,
        ):
            settings = get_settings()
            service = OpenAPIConnectionService(
                repository_factory=repo_factory,
                secret_manager=secret_mgr,
                allow_private_urls=settings.mcp.ALLOW_PRIVATE_URLS,
            )
            deleted = await service.delete_connection(UUID(connection_id))
            return json.dumps({"deleted": deleted})
