"""Service layer for OpenAPI connection management."""

import json
import logging
from typing import Any
from uuid import UUID

import httpx
import yaml

from agentarea_openapi.application.spec_parser import parse_openapi_spec
from agentarea_openapi.application.url_validator import validate_url
from agentarea_openapi.domain.models import OpenAPIConnection
from agentarea_openapi.infrastructure.repository import OpenAPIConnectionRepository

logger = logging.getLogger(__name__)

# Headers that are never sensitive — stored as plaintext.
_SAFE_HEADERS = frozenset(
    h.lower()
    for h in (
        "Accept",
        "Accept-Charset",
        "Accept-Encoding",
        "Accept-Language",
        "Cache-Control",
        "Content-Type",
        "If-Match",
        "If-None-Match",
        "User-Agent",
        "X-Correlation-ID",
        "X-Request-ID",
    )
)


def _secret_key(connection_id: str | UUID, header_name: str) -> str:
    """Build the secret manager key for a header value."""
    return f"openapi:{connection_id}:header:{header_name}"


def _is_safe_header(name: str) -> bool:
    return name.lower() in _SAFE_HEADERS


class OpenAPIConnectionService:
    def __init__(
        self,
        repository_factory: Any,
        secret_manager: Any | None = None,
        allow_private_urls: bool = False,
    ) -> None:
        self._repo: OpenAPIConnectionRepository = repository_factory.create_repository(
            OpenAPIConnectionRepository
        )
        self._secret_manager = secret_manager
        self._allow_private_urls = allow_private_urls

    async def create_connection(
        self,
        name: str,
        base_url: str,
        description: str | None = None,
        spec_url: str | None = None,
        spec_content: dict[str, Any] | None = None,
        auth_config_id: UUID | None = None,
        custom_headers: list[dict[str, str]] | None = None,
    ) -> OpenAPIConnection:
        # Process headers: classify and store secrets
        processed_headers = None
        if custom_headers:
            processed_headers = await self._store_headers(custom_headers, connection_id=None)

        conn = await self._repo.create(
            name=name,
            base_url=base_url,
            description=description,
            spec_url=spec_url,
            spec_content=spec_content,
            auth_config_id=auth_config_id,
            custom_headers=processed_headers,
        )

        # Re-key secrets now that we have the connection ID
        if custom_headers and self._secret_manager:
            await self._rekey_headers(conn, custom_headers)

        return conn

    async def _store_headers(
        self,
        raw_headers: list[dict[str, str]],
        connection_id: str | UUID | None,
    ) -> list[dict[str, Any]]:
        """Classify headers and store secret values.

        Input: [{"name": "Authorization", "value": "Bearer xxx"}, ...]
        Output: [{"name": "Authorization", "secret": true}, ...]
        """
        processed = []
        for h in raw_headers:
            header_name = h.get("name", "").strip()
            header_value = h.get("value", "")
            if not header_name:
                continue

            is_secret = not _is_safe_header(header_name)
            entry: dict[str, Any] = {"name": header_name, "secret": is_secret}

            if is_secret:
                if self._secret_manager is None:
                    raise ValueError(
                        "Secret manager required to store sensitive headers. Configure a secret manager."
                    )
                if connection_id and header_value:
                    key = _secret_key(connection_id, header_name)
                    await self._secret_manager.set_secret(key, header_value)
                # Don't store secret value in DB
            else:
                entry["value"] = header_value

            processed.append(entry)
        return processed

    async def _rekey_headers(
        self,
        conn: OpenAPIConnection,
        raw_headers: list[dict[str, str]],
    ) -> None:
        """After create, store secrets under the real connection ID."""
        if not self._secret_manager:
            return
        for h in raw_headers:
            header_name = h.get("name", "").strip()
            header_value = h.get("value", "")
            if header_name and not _is_safe_header(header_name) and header_value:
                key = _secret_key(conn.id, header_name)
                await self._secret_manager.set_secret(key, header_value)

    async def update_headers(
        self,
        connection_id: UUID,
        raw_headers: list[dict[str, str]],
    ) -> OpenAPIConnection | None:
        """Replace all custom headers on a connection."""
        conn = await self._repo.get_by_id(str(connection_id))
        if not conn:
            return None

        # Clean up old secrets
        await self._delete_header_secrets(conn)

        processed = await self._store_headers(raw_headers, connection_id)
        return await self._repo.update(str(connection_id), custom_headers=processed)

    async def _delete_header_secrets(self, conn: OpenAPIConnection) -> None:
        """Remove all secret header values from the secret manager."""
        if not self._secret_manager or not conn.custom_headers:
            return
        for h in conn.custom_headers:
            if h.get("secret"):
                key = _secret_key(conn.id, h["name"])
                try:
                    await self._secret_manager.delete_secret(key)
                except Exception:
                    logger.warning(f"Failed to delete secret for header {h['name']}")

    async def resolve_headers(self, conn: OpenAPIConnection) -> dict[str, str]:
        """Build the actual HTTP headers dict by resolving secrets."""
        if not conn.custom_headers:
            return {}

        headers: dict[str, str] = {}
        for h in conn.custom_headers:
            name = h["name"]
            if h.get("secret"):
                if self._secret_manager:
                    value = await self._secret_manager.get_secret(
                        _secret_key(conn.id, name)
                    )
                    if value:
                        headers[name] = value
            else:
                value = h.get("value", "")
                if value:
                    headers[name] = value
        return headers

    async def get_connection(self, connection_id: UUID) -> OpenAPIConnection | None:
        return await self._repo.get_by_id(str(connection_id))

    async def list_connections(
        self,
        status: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[OpenAPIConnection], int]:
        return await self._repo.list_connections(
            status=status, search=search, limit=limit, offset=offset
        )

    async def update_connection(
        self, connection_id: UUID, **fields: Any
    ) -> OpenAPIConnection | None:
        return await self._repo.update(str(connection_id), **fields)

    async def delete_connection(self, connection_id: UUID) -> bool:
        conn = await self._repo.get_by_id(str(connection_id))
        if conn:
            await self._delete_header_secrets(conn)
        return await self._repo.delete(str(connection_id))

    async def discover_tools(self, connection_id: UUID) -> dict[str, Any]:
        """Fetch/parse the OpenAPI spec and store discovered tools."""
        conn = await self._repo.get_by_id(str(connection_id))
        if not conn:
            raise ValueError(f"Connection {connection_id} not found")

        spec = conn.spec_content
        if not spec:
            spec = await self._fetch_spec(conn)

        tools = parse_openapi_spec(spec)

        await self._repo.update(str(conn.id), available_tools=tools, spec_content=spec)
        conn = await self._repo.get_by_id(str(conn.id))

        return {
            "connection_id": str(conn.id),
            "tools_discovered": len(tools),
            "tools": [{"name": t["name"], "description": t["description"]} for t in tools],
        }

    async def _fetch_spec(self, conn: OpenAPIConnection) -> dict[str, Any]:
        """Fetch OpenAPI spec from spec_url."""
        if not conn.spec_url:
            raise ValueError(
                f"No spec_url or spec_content for connection {conn.name}. "
                "Provide a spec_url or upload spec_content."
            )

        validate_url(conn.spec_url, allow_private=self._allow_private_urls)
        headers = await self.resolve_headers(conn)
        async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=False) as client:
            resp = await client.get(conn.spec_url)
            resp.raise_for_status()

        content = resp.content
        if len(content) > 5 * 1024 * 1024:
            raise ValueError("Spec response exceeds 5MB limit.")
        text = content.decode(resp.encoding or "utf-8", errors="replace")
        if conn.spec_url.endswith((".yaml", ".yml")):
            return yaml.safe_load(text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return yaml.safe_load(text)

    async def test_connection(self, connection_id: UUID) -> dict[str, Any]:
        """Make a health check request to the base_url."""
        conn = await self._repo.get_by_id(str(connection_id))
        if not conn:
            raise ValueError(f"Connection {connection_id} not found")

        try:
            validate_url(conn.base_url, allow_private=self._allow_private_urls)
            headers = await self.resolve_headers(conn)
            async with httpx.AsyncClient(timeout=10, headers=headers, follow_redirects=False) as client:
                resp = await client.get(conn.base_url)
            return {
                "status": "reachable",
                "status_code": resp.status_code,
            }
        except httpx.RequestError as e:
            return {
                "status": "unreachable",
                "error": str(e),
            }
