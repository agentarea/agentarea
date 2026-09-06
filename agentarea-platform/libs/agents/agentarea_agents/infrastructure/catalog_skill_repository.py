"""Read-only access to built-in skills that live in the registry catalog.

Per ADR-003, built-in/official skills are not materialized into the ``skills``
table; they are ``registry_items`` of ``registry_type='skills'`` whose full
definition lives in the item's ``spec`` JSONB. This repository reads those
catalog items so the skill service can project them as read-only skills.

It deliberately uses raw SQL against ``registry_items`` / ``registries`` to avoid
a cross-library dependency on ``agentarea-registry``. The catalog is global
infrastructure (ADR-003): registries/registry_items are not workspace-scoped, so
every tenant reads the same built-in skill definitions with no workspace filter.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from agentarea_common.auth.context import UserContext
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class CatalogSkillItem:
    """A built-in skill definition projected from a registry item."""

    id: str
    name: str
    description: str | None
    version: str | None
    spec: dict[str, Any]
    installed_entity_id: str | None
    installed_version: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CatalogSkillSummary:
    """List-view row for a catalog skill: metadata only, never the skill body.

    ``SkillResponse`` does not carry skill content, so the list read path reads
    the handful of scalar keys it needs out of ``spec`` in SQL instead of
    loading every item's full JSONB definition into the API process.
    """

    id: str
    name: str
    description: str | None
    version: str | None
    source_type: str
    source_url: str | None
    network_scope: str
    installed_version: str | None
    created_at: datetime
    updated_at: datetime


class CatalogSkillRepository:
    """Reads built-in skill definitions from the registry catalog."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.user_context = user_context

    async def list_items(self) -> list[CatalogSkillItem]:
        """List all catalog skill items (global catalog, no workspace filter)."""
        query = text(
            "SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, "
            "rii.installed_entity_id, rii.installed_version, "
            "ri.created_at, ri.updated_at "
            "FROM registry_items ri "
            "JOIN registries r ON r.id = ri.registry_id "
            "LEFT JOIN registry_item_installs rii "
            "  ON rii.registry_item_id = ri.id "
            " AND rii.workspace_id = :workspace_id "
            "WHERE r.registry_type = 'skills' "
            "ORDER BY ri.name"
        )
        result = await self.session.execute(query, {"workspace_id": self.user_context.workspace_id})
        return [self._row_to_item(row) for row in result.fetchall()]

    async def list_page(
        self,
        *,
        limit: int,
        offset: int,
        exclude_item_ids: Collection[str],
        search: str | None = None,
        source_type: str | None = None,
        network_scope: str | None = None,
    ) -> tuple[list[CatalogSkillSummary], int]:
        """Page the catalog in SQL, returning ``(rows, total_matching)``.

        ``exclude_item_ids`` drops items the workspace has already forked, so
        the tenant copy shadows them exactly as the merged list expects.
        """
        where = ["r.registry_type = 'skills'"]
        params: dict[str, Any] = {"workspace_id": self.user_context.workspace_id}

        if exclude_item_ids:
            where.append("ri.id::text NOT IN :exclude_ids")
            params["exclude_ids"] = tuple(str(i) for i in exclude_item_ids)
        if search:
            where.append(
                "(ri.name ILIKE :search OR ri.description ILIKE :search "
                "OR ri.spec->>'source_url' ILIKE :search)"
            )
            params["search"] = f"%{search.strip()}%"
        if source_type:
            where.append("COALESCE(ri.spec->>'source_type', 'content') = :source_type")
            params["source_type"] = source_type
        if network_scope:
            where.append("COALESCE(ri.spec->>'network_scope', 'private') = :network_scope")
            params["network_scope"] = network_scope

        where_sql = " AND ".join(where)
        joins = (
            "FROM registry_items ri "
            "JOIN registries r ON r.id = ri.registry_id "
            "LEFT JOIN registry_item_installs rii "
            "  ON rii.registry_item_id = ri.id "
            " AND rii.workspace_id = :workspace_id "
            f"WHERE {where_sql}"
        )

        count_stmt = self._bind(text(f"SELECT COUNT(*) {joins}"), params)
        total = (await self.session.execute(count_stmt, params)).scalar_one()

        rows_stmt = self._bind(
            text(
                "SELECT ri.id, ri.name, "
                "COALESCE(ri.description, ri.spec->>'description') AS description, "
                "ri.version, "
                "COALESCE(ri.spec->>'source_type', 'content') AS source_type, "
                "ri.spec->>'source_url' AS source_url, "
                "COALESCE(ri.spec->>'network_scope', 'private') AS network_scope, "
                "rii.installed_version, ri.created_at, ri.updated_at "
                f"{joins} "
                "ORDER BY ri.name, ri.id "
                "LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        result = await self.session.execute(rows_stmt, {**params, "limit": limit, "offset": offset})
        return [self._row_to_summary(row) for row in result.fetchall()], total

    async def versions_for(
        self, item_ids: Collection[str]
    ) -> dict[str, tuple[str | None, str | None]]:
        """Map catalog item id to ``(catalog_version, installed_version)``.

        Used to flag an already-forked tenant skill as out of date without
        reading the rest of the catalog.
        """
        if not item_ids:
            return {}
        stmt = text(
            "SELECT ri.id, ri.version, rii.installed_version "
            "FROM registry_items ri "
            "JOIN registries r ON r.id = ri.registry_id "
            "LEFT JOIN registry_item_installs rii "
            "  ON rii.registry_item_id = ri.id "
            " AND rii.workspace_id = :workspace_id "
            "WHERE r.registry_type = 'skills' AND ri.id::text IN :item_ids"
        ).bindparams(bindparam("item_ids", expanding=True))
        result = await self.session.execute(
            stmt,
            {
                "workspace_id": self.user_context.workspace_id,
                "item_ids": tuple(str(i) for i in item_ids),
            },
        )
        return {str(row.id): (row.version, row.installed_version) for row in result.fetchall()}

    @staticmethod
    def _bind(stmt: Any, params: dict[str, Any]) -> Any:
        """Mark the id-exclusion parameter as expanding when it is present."""
        if "exclude_ids" in params:
            return stmt.bindparams(bindparam("exclude_ids", expanding=True))
        return stmt

    async def get_item(self, item_id: str) -> CatalogSkillItem | None:
        """Get a single catalog skill item by its registry-item id."""
        query = text(
            "SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, "
            "rii.installed_entity_id, rii.installed_version, "
            "ri.created_at, ri.updated_at "
            "FROM registry_items ri "
            "JOIN registries r ON r.id = ri.registry_id "
            "LEFT JOIN registry_item_installs rii "
            "  ON rii.registry_item_id = ri.id "
            " AND rii.workspace_id = :workspace_id "
            "WHERE r.registry_type = 'skills' "
            "AND ri.id = :item_id"
        )
        result = await self.session.execute(
            query,
            {"item_id": item_id, "workspace_id": self.user_context.workspace_id},
        )
        row = result.fetchone()
        return self._row_to_item(row) if row else None

    async def mark_installed(
        self, item_id: str, entity_id: str, installed_version: str | None
    ) -> None:
        """Record the workspace materialization of a catalog skill item."""
        await self.session.execute(
            text(
                "INSERT INTO registry_item_installs "
                "(id, registry_item_id, workspace_id, installed_entity_id, installed_version, "
                "created_at, updated_at) "
                "VALUES (:install_id, :item_id, :workspace_id, :eid, :ver, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
                "ON CONFLICT (registry_item_id, workspace_id) DO UPDATE SET "
                "installed_entity_id = EXCLUDED.installed_entity_id, "
                "installed_version = EXCLUDED.installed_version, "
                "updated_at = CURRENT_TIMESTAMP"
            ),
            {
                "eid": entity_id,
                "install_id": str(uuid4()),
                "ver": installed_version,
                "item_id": item_id,
                "workspace_id": self.user_context.workspace_id,
            },
        )

    @staticmethod
    def _row_to_summary(row: Any) -> CatalogSkillSummary:
        created_at = row.created_at or row.updated_at or datetime.utcnow()
        return CatalogSkillSummary(
            id=str(row.id),
            name=row.name,
            description=row.description,
            version=row.version,
            source_type=row.source_type,
            source_url=row.source_url,
            network_scope=row.network_scope,
            installed_version=row.installed_version,
            created_at=created_at,
            updated_at=row.updated_at or created_at,
        )

    @staticmethod
    def _row_to_item(row: Any) -> CatalogSkillItem:
        spec = row.spec if isinstance(row.spec, dict) else {}
        created_at = row.created_at or row.updated_at or datetime.utcnow()
        return CatalogSkillItem(
            id=str(row.id),
            name=row.name,
            description=row.description,
            version=row.version,
            spec=spec,
            installed_entity_id=str(row.installed_entity_id) if row.installed_entity_id else None,
            installed_version=row.installed_version,
            created_at=created_at,
            updated_at=row.updated_at or created_at,
        )
