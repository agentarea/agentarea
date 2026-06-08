"""Read-only access to built-in model specs that live in the registry catalog.

Per ADR-003, built-in/official model specs are not materialized into the
``model_specs`` table; they are ``registry_items`` of
``registry_type='llm_models'`` whose full definition lives in the item's
``spec`` JSONB. This repository reads those catalog items so the model-spec read
path can project them as read-only reference specs.

A catalog model spec carries a ``provider_key`` (e.g. ``openai``). The matching
DB ``provider_specs.id`` is resolved here by joining ``provider_specs`` on that
key so the projected model spec can populate ``provider_spec_id`` /
``provider_name`` / ``provider_key`` for the API. provider_specs remain real DB
rows (they are not catalog-only in this change).

Unlike agents/skills, model specs are NOT forked on edit: they are reference
specs that users instantiate via ``model_instances`` rather than editing the
spec itself. So there is no copy-on-write here -- the catalog is a pure read
source merged into the spec list.

It deliberately uses raw SQL against ``registry_items`` / ``registries`` to avoid
a cross-library dependency on ``agentarea-registry``. The catalog is global
infrastructure (ADR-003): registries/registry_items are not workspace-scoped, so
every tenant reads the same built-in spec definitions with no workspace filter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentarea_common.auth.context import UserContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class CatalogModelSpecItem:
    """A built-in model spec definition projected from a registry item."""

    id: str
    name: str
    description: str | None
    version: str | None
    spec: dict[str, Any]
    provider_spec_id: str | None
    provider_key: str | None
    provider_name: str | None


class CatalogModelSpecRepository:
    """Reads built-in model spec definitions from the registry catalog."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.user_context = user_context

    async def list_items(self) -> list[CatalogModelSpecItem]:
        """List all catalog model spec items (global catalog, no workspace filter).

        The catalog item's ``spec.provider_key`` is resolved against the
        ``provider_specs`` table (LEFT JOIN on ``spec->>'provider_key'``) so the
        projection can carry the DB ``provider_spec_id`` the API needs.
        """
        query = text(
            "SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, "
            "ps.id AS provider_spec_id, ps.provider_key, ps.name AS provider_name "
            "FROM registry_items ri "
            "JOIN registries r ON r.id = ri.registry_id "
            "LEFT JOIN provider_specs ps ON ps.provider_key = ri.spec->>'provider_key' "
            "WHERE r.registry_type = 'llm_models' "
            "ORDER BY ri.name"
        )
        result = await self.session.execute(query)
        return [self._row_to_item(row) for row in result.fetchall()]

    async def get_item(self, item_id: str) -> CatalogModelSpecItem | None:
        """Get a single catalog model spec item by its registry-item id."""
        query = text(
            "SELECT ri.id, ri.name, ri.description, ri.version, ri.spec, "
            "ps.id AS provider_spec_id, ps.provider_key, ps.name AS provider_name "
            "FROM registry_items ri "
            "JOIN registries r ON r.id = ri.registry_id "
            "LEFT JOIN provider_specs ps ON ps.provider_key = ri.spec->>'provider_key' "
            "WHERE r.registry_type = 'llm_models' "
            "AND ri.id = :item_id"
        )
        result = await self.session.execute(query, {"item_id": item_id})
        row = result.fetchone()
        return self._row_to_item(row) if row else None

    @staticmethod
    def _row_to_item(row: Any) -> CatalogModelSpecItem:
        spec = row.spec if isinstance(row.spec, dict) else {}
        return CatalogModelSpecItem(
            id=str(row.id),
            name=row.name,
            description=row.description,
            version=row.version,
            spec=spec,
            provider_spec_id=str(row.provider_spec_id) if row.provider_spec_id else None,
            provider_key=row.provider_key or spec.get("provider_key"),
            provider_name=row.provider_name,
        )
