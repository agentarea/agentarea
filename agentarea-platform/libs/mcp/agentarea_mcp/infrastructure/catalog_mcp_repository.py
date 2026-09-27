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

import json
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from sqlalchemy import bindparam, text
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

    async def list_page(
        self,
        *,
        limit: int,
        offset: int,
        exclude_item_ids: Collection[str],
        tag: str | None = None,
        search: str | None = None,
        item_ids: Collection[str] | None = None,
    ) -> tuple[list[CatalogMcpItem], int]:
        """Page the catalog in SQL, returning ``(items, total_matching)``.

        Filters on the registry type and active flag each item carries, which
        the partial browse indexes serve. ``exclude_item_ids`` drops items a
        tenant spec already instantiates; ``item_ids`` keeps only those items.
        """
        where = ["ri.registry_type = 'mcp_servers'", "ri.registry_active"]
        params: dict[str, Any] = {}
        expanding: list[str] = []

        if item_ids is not None:
            where.append("ri.id IN :item_ids")
            params["item_ids"] = [UUID(str(i)) for i in item_ids]
            expanding.append("item_ids")
        if exclude_item_ids:
            where.append("ri.id NOT IN :exclude_ids")
            params["exclude_ids"] = [UUID(str(i)) for i in exclude_item_ids]
            expanding.append("exclude_ids")
        if tag is not None:
            where.append("ri.tags @> CAST(:tag AS jsonb)")
            params["tag"] = json.dumps([tag])
        if search is not None:
            where.append("(ri.name ILIKE :search OR COALESCE(ri.description, '') ILIKE :search)")
            params["search"] = f"%{search}%"

        # Only the fixed clauses above are interpolated; every value is bound.
        where_sql = " AND ".join(where)
        bind = [bindparam(name, expanding=True) for name in expanding]
        total = (
            await self.session.execute(
                text(
                    f"SELECT COUNT(*) FROM registry_items ri WHERE {where_sql}"  # noqa: S608
                ).bindparams(*bind),
                params,
            )
        ).scalar_one()
        if limit <= 0 or offset >= total:
            return [], total

        rows = await self.session.execute(
            text(
                "SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, ri.tags, "  # noqa: S608
                "ri.created_at, ri.updated_at "
                f"FROM registry_items ri WHERE {where_sql} "
                "ORDER BY ri.sort_key, ri.id "
                "LIMIT :limit OFFSET :offset"
            ).bindparams(*bind),
            {**params, "limit": limit, "offset": offset},
        )
        return [self._row_to_item(row, registry_url=None) for row in rows.fetchall()], total

    async def get_item(self, item_id: str) -> CatalogMcpItem | None:
        """Get a single catalog MCP server item by its registry-item id."""
        query = text(
            "SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, ri.tags, "
            "ri.created_at, ri.updated_at "
            "FROM registry_items ri "
            "JOIN registries r ON r.id = ri.registry_id "
            "WHERE r.registry_type = 'mcp_servers' AND r.is_active "
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
