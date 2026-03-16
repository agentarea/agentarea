"""Service layer for OpenAPI connection management."""

import json
import logging
from typing import Any
from uuid import UUID

import httpx
import yaml

from agentarea_openapi.application.spec_parser import parse_openapi_spec
from agentarea_openapi.domain.models import OpenAPIConnection
from agentarea_openapi.infrastructure.repository import OpenAPIConnectionRepository

logger = logging.getLogger(__name__)


class OpenAPIConnectionService:
    def __init__(
        self,
        repository_factory: Any,
        secret_manager: Any | None = None,
    ) -> None:
        self._repo: OpenAPIConnectionRepository = repository_factory.create_repository(
            OpenAPIConnectionRepository
        )
        self._secret_manager = secret_manager

    async def create_connection(
        self,
        name: str,
        base_url: str,
        description: str | None = None,
        spec_url: str | None = None,
        spec_content: dict[str, Any] | None = None,
        auth_config_id: UUID | None = None,
    ) -> OpenAPIConnection:
        return await self._repo.create(
            name=name,
            base_url=base_url,
            description=description,
            spec_url=spec_url,
            spec_content=spec_content,
            auth_config_id=auth_config_id,
        )

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

        conn.available_tools = tools
        conn.spec_content = spec
        await self._repo.session.commit()
        await self._repo.session.refresh(conn)

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

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(conn.spec_url)
            resp.raise_for_status()

        text = resp.text
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
            async with httpx.AsyncClient(timeout=10) as client:
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
