"""Event source types from the registry catalog (ADR-0040 §2).

A source type is a ``registry_items`` row of ``registry_type='source_types'``
whose ``spec`` is the whole entry; its ``external_id`` is the slug. The catalog
is global (ADR-003), so there is no workspace filter. Raw SQL, like
``CatalogAgentRepository``, so streams need not depend on the registry library.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.source_types import SourceTypeEntry

logger = logging.getLogger(__name__)

_SELECT = (
    "SELECT ri.external_id, ri.spec "
    "FROM registry_items ri "
    "WHERE ri.registry_type = 'source_types' AND ri.registry_active "
)


class CatalogSourceTypeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_entries(self) -> list[SourceTypeEntry]:
        """Every source type, by name; one entry per slug (the highest-priority registry's)."""
        result = await self.session.execute(
            text(_SELECT + "ORDER BY ri.registry_priority, ri.recommendation_rank, ri.name")
        )
        entries: dict[str, SourceTypeEntry] = {}
        for row in result.fetchall():
            entry = self._entry(row.external_id, row.spec)
            if entry is not None and entry.slug not in entries:
                entries[entry.slug] = entry
        return sorted(entries.values(), key=lambda e: e.name.lower())

    async def get(self, slug: str) -> SourceTypeEntry | None:
        result = await self.session.execute(
            text(_SELECT + "AND ri.external_id = :slug ORDER BY ri.registry_priority"),
            {"slug": slug},
        )
        for row in result.fetchall():
            entry = self._entry(row.external_id, row.spec)
            if entry is not None:
                return entry
        return None

    @staticmethod
    def _entry(external_id: str, spec: Any) -> SourceTypeEntry | None:
        try:
            return SourceTypeEntry.model_validate(spec)
        except ValidationError:
            # One malformed catalog row must not take every source type down with it.
            logger.error("Catalog source type %r is not a valid entry", external_id, exc_info=True)
            return None
