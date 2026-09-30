"""Read-only access to built-in skills that live in the registry catalog.

Per ADR-003, built-in/official skills are not materialized into the ``skills``
table; they are ``registry_items`` of ``registry_type='skills'`` whose full
definition lives in the item's ``spec`` JSONB. This repository reads those
catalog items so the skill service can project them as read-only skills.

It deliberately uses raw SQL against ``registry_items`` to avoid a
cross-library dependency on ``agentarea-registry``. The catalog is global
infrastructure (ADR-003): registries/registry_items are not workspace-scoped, so
every tenant reads the same built-in skill definitions with no workspace filter.

Every read filters on the registry type and active flag each item carries, as
the bare ``registry_active`` column: that is the predicate of the partial browse
indexes, and joining ``registries`` instead leaves the planner no index to use.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

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
            "LEFT JOIN registry_item_installs rii "
            "  ON rii.registry_item_id = ri.id "
            " AND rii.workspace_id = :workspace_id "
            "WHERE ri.registry_type = 'skills' AND ri.registry_active "
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

        Pages in the browse order (``sort_key``) so the page and its total are
        read from the partial browse indexes. ``exclude_item_ids`` drops items
        the workspace has already forked, so the tenant copy shadows them
        exactly as the merged list expects.
        """
        where = ["ri.registry_type = 'skills'", "ri.registry_active"]
        params: dict[str, Any] = {}
        expanding: list[str] = []

        if exclude_item_ids:
            where.append("ri.id NOT IN :exclude_ids")
            params["exclude_ids"] = [UUID(str(i)) for i in exclude_item_ids]
            expanding.append("exclude_ids")
        if search:
            # The columns the trigram indexes cover, as /explore searches.
            where.append("(ri.name ILIKE :search OR ri.description ILIKE :search)")
            params["search"] = f"%{search.strip()}%"
        if source_type:
            where.append("COALESCE(ri.spec->>'source_type', 'content') = :source_type")
            params["source_type"] = source_type
        if network_scope:
            where.append("COALESCE(ri.spec->>'network_scope', 'private') = :network_scope")
            params["network_scope"] = network_scope

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

        result = await self.session.execute(
            text(
                "SELECT ri.id, ri.name, "  # noqa: S608
                "COALESCE(ri.description, ri.spec->>'description') AS description, "
                "ri.version, "
                "COALESCE(ri.spec->>'source_type', 'content') AS source_type, "
                "ri.spec->>'source_url' AS source_url, "
                "COALESCE(ri.spec->>'network_scope', 'private') AS network_scope, "
                "ri.created_at, ri.updated_at "
                f"FROM registry_items ri WHERE {where_sql} "
                "ORDER BY ri.sort_key, ri.id "
                "LIMIT :limit OFFSET :offset"
            ).bindparams(*bind),
            {**params, "limit": limit, "offset": offset},
        )
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
            "LEFT JOIN registry_item_installs rii "
            "  ON rii.registry_item_id = ri.id "
            " AND rii.workspace_id = :workspace_id "
            "WHERE ri.registry_type = 'skills' AND ri.registry_active AND ri.id IN :item_ids"
        ).bindparams(bindparam("item_ids", expanding=True))
        result = await self.session.execute(
            stmt,
            {
                "workspace_id": self.user_context.workspace_id,
                "item_ids": [UUID(str(i)) for i in item_ids],
            },
        )
        return {str(row.id): (row.version, row.installed_version) for row in result.fetchall()}

    async def get_item(self, item_id: str) -> CatalogSkillItem | None:
        """Get a single catalog skill item by its registry-item id."""
        query = text(
            "SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, "
            "rii.installed_entity_id, rii.installed_version, "
            "ri.created_at, ri.updated_at "
            "FROM registry_items ri "
            "LEFT JOIN registry_item_installs rii "
            "  ON rii.registry_item_id = ri.id "
            " AND rii.workspace_id = :workspace_id "
            "WHERE ri.registry_type = 'skills' AND ri.registry_active "
            "AND ri.id = :item_id"
        )
        result = await self.session.execute(
            query,
            {"item_id": item_id, "workspace_id": self.user_context.workspace_id},
        )
        row = result.fetchone()
        return self._row_to_item(row) if row else None

    async def find_by_key(self, key: str) -> CatalogSkillItem | None:
        """The newest catalog skill whose name is ``key`` or ``key--<content hash>``.

        Catalog skill names end in a content hash that changes when the skill is
        republished, and one skill can appear in several shards. The part before
        the hash (``<skill>--<source>``) is stable, so presets reference that.
        """
        query = text(
            "SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, "
            "rii.installed_entity_id, rii.installed_version, "
            "ri.created_at, ri.updated_at "
            "FROM registry_items ri "
            "LEFT JOIN registry_item_installs rii "
            "  ON rii.registry_item_id = ri.id "
            " AND rii.workspace_id = :workspace_id "
            "WHERE ri.registry_type = 'skills' AND ri.registry_active "
            "AND (ri.name = :key OR ri.name LIKE :prefix) "
            "ORDER BY ri.updated_at DESC, ri.id "
            "LIMIT 1"
        )
        result = await self.session.execute(
            query,
            {
                "key": key,
                "prefix": key.replace("%", r"\%").replace("_", r"\_") + "--%",
                "workspace_id": self.user_context.workspace_id,
            },
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
