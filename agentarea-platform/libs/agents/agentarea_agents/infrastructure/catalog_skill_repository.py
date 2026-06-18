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

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from agentarea_common.auth.context import UserContext
from sqlalchemy import text
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
