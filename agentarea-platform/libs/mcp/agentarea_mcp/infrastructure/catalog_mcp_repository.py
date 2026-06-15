"""Read-only access to built-in MCP server specs that live in the registry catalog.

Per ADR-003, built-in/official MCP server specs are not materialized into the
``mcp_servers`` table; they are ``registry_items`` of
``registry_type='mcp_servers'`` whose full definition lives in the item's
``spec`` JSONB. This repository reads those catalog items so the MCP server
service can project them as read-only reference specs.

Unlike agents/skills, MCP server specs are NOT forked on edit: they are
reference specs that users instantiate via ``mcp_server_instances`` rather than
editing the spec itself. So there is no copy-on-write here -- the catalog is a
pure read source merged into the spec list.

It deliberately uses raw SQL against ``registry_items`` / ``registries`` to avoid
a cross-library dependency on ``agentarea-registry``. The catalog is global
infrastructure (ADR-003): registries/registry_items are not workspace-scoped, so
every tenant reads the same built-in spec definitions with no workspace filter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agentarea_common.auth.context import UserContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class CatalogMcpItem:
    """A built-in MCP server spec definition projected from a registry item."""

    id: str
    name: str
    description: str | None
    version: str | None
    spec: dict[str, Any]
    tags: list[str]
    registry_url: str | None
    created_at: datetime
    updated_at: datetime


class CatalogMcpRepository:
    """Reads built-in MCP server spec definitions from the registry catalog."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.user_context = user_context

    async def list_items(self) -> list[CatalogMcpItem]:
        """List all catalog MCP server items (global catalog, no workspace filter)."""
        query = text(
            "SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, ri.tags, "
            "ri.created_at, ri.updated_at "
            "FROM registry_items ri "
            "JOIN registries r ON r.id = ri.registry_id "
            "WHERE r.registry_type = 'mcp_servers' AND r.is_active "
            "ORDER BY ri.name"
        )
        result = await self.session.execute(query)
        return [self._row_to_item(row, registry_url=None) for row in result.fetchall()]

    async def get_item(self, item_id: str) -> CatalogMcpItem | None:
        """Get a single catalog MCP server item by its registry-item id."""
        query = text(
            "SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, ri.tags, "
            "ri.created_at, ri.updated_at "
            "FROM registry_items ri "
            "JOIN registries r ON r.id = ri.registry_id "
            "WHERE r.registry_type = 'mcp_servers' "
            "AND ri.id = :item_id"
        )
        result = await self.session.execute(query, {"item_id": item_id})
        row = result.fetchone()
        return self._row_to_item(row, registry_url=None) if row else None

    @staticmethod
    def _row_to_item(row: Any, registry_url: str | None) -> CatalogMcpItem:
        spec = row.spec if isinstance(row.spec, dict) else {}
        tags = row.tags if isinstance(row.tags, list) else []
        created_at = row.created_at or row.updated_at or datetime.utcnow()
        updated_at = row.updated_at or created_at
        return CatalogMcpItem(
            id=str(row.id),
            name=row.name,
            description=row.description,
            version=row.version,
            spec=spec,
            tags=tags,
            registry_url=spec.get("registry_url") or registry_url,
            created_at=created_at,
            updated_at=updated_at,
        )
