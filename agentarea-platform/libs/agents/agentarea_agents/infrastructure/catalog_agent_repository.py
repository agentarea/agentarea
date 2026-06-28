"""Read-only access to built-in agents that live in the registry catalog.

Per ADR-003, built-in/official agents are not materialized into the ``agents``
table; they are ``registry_items`` of ``registry_type='agents'`` whose full
definition lives in the item's ``spec`` JSONB. This repository reads those
catalog items so the agent service can project them as read-only agents.

It deliberately uses raw SQL against ``registry_items`` / ``registries`` to avoid
a cross-library dependency on ``agentarea-registry``. The catalog is global
infrastructure (ADR-003): registries/registry_items are not workspace-scoped, so
every tenant reads the same built-in agent definitions with no workspace filter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from agentarea_common.auth.context import UserContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def pick_model_instance_id(
    preferred_models: list[str], instance_ids_by_name: dict[str, str]
) -> str | None:
    """Pick the instance id for the first preferred model that has one.

    ``preferred_models`` is a priority-ordered list of model slugs;
    ``instance_ids_by_name`` maps model slug to a workspace model-instance id.
    Returns ``None`` when no preferred model is configured in the workspace.
    """
    for name in preferred_models:
        instance_id = instance_ids_by_name.get(name)
        if instance_id is not None:
            return instance_id
    return None


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

    async def list_items(self) -> list[CatalogAgentItem]:
        """List all catalog agent items (global catalog, no workspace filter)."""
        query = text(
            "SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, "
            "rii.installed_entity_id, rii.installed_version "
            "FROM registry_items ri "
            "JOIN registries r ON r.id = ri.registry_id "
            "LEFT JOIN registry_item_installs rii "
            "  ON rii.registry_item_id = ri.id "
            " AND rii.workspace_id = :workspace_id "
            "WHERE r.registry_type = 'agents' "
            "ORDER BY ri.name"
        )
        result = await self.session.execute(query, {"workspace_id": self.user_context.workspace_id})
        return [self._row_to_item(row) for row in result.fetchall()]

    async def get_item(self, item_id: str) -> CatalogAgentItem | None:
        """Get a single catalog agent item by its registry-item id."""
        query = text(
            "SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, "
            "rii.installed_entity_id, rii.installed_version "
            "FROM registry_items ri "
            "JOIN registries r ON r.id = ri.registry_id "
            "LEFT JOIN registry_item_installs rii "
            "  ON rii.registry_item_id = ri.id "
            " AND rii.workspace_id = :workspace_id "
            "WHERE r.registry_type = 'agents' "
            "AND ri.id = :item_id"
        )
        result = await self.session.execute(
            query,
            {"item_id": item_id, "workspace_id": self.user_context.workspace_id},
        )
        row = result.fetchone()
        return self._row_to_item(row) if row else None

    async def model_instance_ids_by_name(self) -> dict[str, str]:
        """Map ``model_specs.model_name`` to an active model-instance id for this workspace.

        Catalog agents are global and reference models by slug (e.g. ``gpt-4o``),
        but the runnable ``model_id`` is a per-workspace ``model_instances`` row.
        The first active instance per model name wins. Use this to resolve many
        catalog items without an N+1 query.

        Uses raw SQL against the LLM tables to avoid a cross-library dependency on
        ``agentarea-llm`` (same rationale as the registry reads above).
        """
        query = text(
            "SELECT ms.model_name, mi.id "
            "FROM model_instances mi "
            "JOIN model_specs ms ON ms.id = mi.model_spec_id "
            "WHERE mi.workspace_id = :workspace_id "
            "AND mi.is_active = true"
        )
        result = await self.session.execute(
            query, {"workspace_id": self.user_context.workspace_id}
        )
        by_name: dict[str, str] = {}
        for row in result.fetchall():
            by_name.setdefault(row.model_name, str(row.id))
        return by_name

    async def resolve_model_instance_id(self, preferred_models: list[str]) -> str | None:
        """Resolve preferred model slugs to a single workspace model-instance id.

        Walks ``preferred_models`` in priority order and returns the id of the
        first matching active instance, or ``None`` when nothing matches (so the
        agent installs without a bound model).
        """
        if not preferred_models:
            return None
        return pick_model_instance_id(preferred_models, await self.model_instance_ids_by_name())

    async def mark_installed(
        self, item_id: str, entity_id: str, installed_version: str | None
    ) -> None:
        """Record the workspace materialization of a catalog agent item."""
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
    def _row_to_item(row: Any) -> CatalogAgentItem:
        spec = row.spec if isinstance(row.spec, dict) else {}
        return CatalogAgentItem(
            id=str(row.id),
            name=row.name,
            description=row.description,
            version=row.version,
            spec=spec,
            installed_entity_id=str(row.installed_entity_id) if row.installed_entity_id else None,
            installed_version=row.installed_version,
        )
