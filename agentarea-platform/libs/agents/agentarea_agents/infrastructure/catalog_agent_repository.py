"""Read-only access to built-in agents that live in the registry catalog.

Per ADR-003, built-in/official agents are not materialized into the ``agents``
table; they are ``registry_items`` of ``registry_type='agents'`` whose full
definition lives in the item's ``spec`` JSONB. This repository reads those
catalog items so the agent service can project them as read-only agents.

It deliberately uses raw SQL against ``registry_items`` / ``registries`` to avoid
a cross-library dependency on ``agentarea-registry``. Reads are scoped to the
caller's accessible workspaces (the ``platform`` workspace is injected there by
the authorization layer, which is what makes the catalog globally readable).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentarea_common.auth.context import UserContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class CatalogAgentItem:
    """A built-in agent definition projected from a registry item."""

    id: str
    name: str
    description: str | None
    version: str | None
    spec: dict[str, Any]
    installed_entity_id: str | None
    installed_version: str | None


class CatalogAgentRepository:
    """Reads built-in agent definitions from the registry catalog."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.user_context = user_context

    def _accessible_workspaces(self) -> list[str]:
        workspaces = self.user_context.accessible_workspaces
        if workspaces:
            return list(workspaces)
        return [self.user_context.workspace_id]

    async def list_items(self) -> list[CatalogAgentItem]:
        """List all catalog agent items readable by the current user."""
        query = text(
            "SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, "
            "ri.installed_entity_id, ri.installed_version "
            "FROM registry_items ri "
            "JOIN registries r ON r.id = ri.registry_id "
            "WHERE r.registry_type = 'agents' "
            "AND ri.workspace_id = ANY(:workspaces) "
            "ORDER BY ri.name"
        )
        result = await self.session.execute(
            query, {"workspaces": self._accessible_workspaces()}
        )
        return [self._row_to_item(row) for row in result.fetchall()]

    async def get_item(self, item_id: str) -> CatalogAgentItem | None:
        """Get a single catalog agent item by its registry-item id."""
        query = text(
            "SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, "
            "ri.installed_entity_id, ri.installed_version "
            "FROM registry_items ri "
            "JOIN registries r ON r.id = ri.registry_id "
            "WHERE r.registry_type = 'agents' "
            "AND ri.id = :item_id "
            "AND ri.workspace_id = ANY(:workspaces)"
        )
        result = await self.session.execute(
            query, {"item_id": item_id, "workspaces": self._accessible_workspaces()}
        )
        row = result.fetchone()
        return self._row_to_item(row) if row else None

    async def mark_installed(
        self, item_id: str, entity_id: str, installed_version: str | None
    ) -> None:
        """Record the materialized tenant copy of a catalog agent item."""
        await self.session.execute(
            text(
                "UPDATE registry_items SET installed_entity_id = :eid, "
                "installed_version = :ver, updated_at = now() WHERE id = :item_id"
            ),
            {"eid": entity_id, "ver": installed_version, "item_id": item_id},
        )

    @staticmethod
    def _row_to_item(row: Any) -> CatalogAgentItem:
        spec = row.spec if isinstance(row.spec, dict) else {}
        return CatalogAgentItem(
            id=str(row.id),
            name=row.name,
            description=row.description,
            version=row.version,
            spec=spec,
            installed_entity_id=str(row.installed_entity_id)
            if row.installed_entity_id
            else None,
            installed_version=row.installed_version,
        )
