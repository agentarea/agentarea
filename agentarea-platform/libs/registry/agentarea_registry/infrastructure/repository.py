"""Repositories for Registry and RegistryItem domain models.

Registries and registry_items are GLOBAL catalog infrastructure (ADR-003), not
workspace-scoped: built-in/official content lives here once and is readable by
every tenant. These repositories therefore apply no workspace filter and never
set workspace_id/created_by. They keep the ``(session, user_context)`` signature
for call-site compatibility, but ``user_context`` is intentionally unused for
read/write scoping.
"""

from typing import Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from agentarea_registry.domain.models import Registry, RegistryItem

# Accepted catalog orderings, mapped to their ORDER BY. Every ordering ends with
# ``id`` so rows with equal keys can't let OFFSET paging repeat one and drop
# another. Public: the API validates ``sort`` against these names rather than
# silently ignoring an unknown one, and the webapp mirrors them in SORT_KEYS.
CATALOG_SORTS: dict[str, Any] = {
    "featured": lambda: (
        RegistryItem.featured.desc(),
        RegistryItem.sort_key.asc(),
        RegistryItem.id.asc(),
    ),
    "name": lambda: (RegistryItem.sort_key.asc(), RegistryItem.id.asc()),
}
DEFAULT_CATALOG_SORT = "featured"

# The category sources fall back to when they can't classify an entry. It is a
# bucket, not a peer category, so the facet list sorts it last rather than
# letting it land mid-alphabet or -- as ordering by size did -- near the top.
FALLBACK_CATEGORY = "other"


class RegistryRepository:
    """Global (non-scoped) repository for Registry rows."""

    def __init__(self, session: AsyncSession, user_context: UserContext | None = None):
        self.session = session
        self.user_context = user_context
        self.model_class = Registry

    async def get_by_id(self, id: UUID | str) -> Registry | None:
        return await self.session.get(Registry, id)

    async def list_all(
        self, limit: int | None = None, offset: int | None = None, **filters: Any
    ) -> list[Registry]:
        query = select(Registry)
        for field, value in filters.items():
            if hasattr(Registry, field):
                query = query.where(getattr(Registry, field) == value)
        query = query.order_by(Registry.created_at.desc())
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def list_active(self, registry_type: str | None = None) -> list[Registry]:
        filters: dict = {"is_active": True}
        if registry_type:
            filters["registry_type"] = registry_type
        return await self.list_all(**filters)

    async def create(self, **kwargs: Any) -> Registry:
        record = Registry(**kwargs)
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def update(self, id: UUID | str, **kwargs: Any) -> Registry | None:
        record = await self.session.get(Registry, id)
        if record is None:
            return None
        for field, value in kwargs.items():
            if hasattr(record, field):
                setattr(record, field, value)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def delete(self, id: UUID | str) -> bool:
        record = await self.session.get(Registry, id)
        if record is None:
            return False
        await self.session.delete(record)
        await self.session.commit()
        return True


class RegistryItemRepository:
    """Global (non-scoped) repository for RegistryItem rows."""

    def __init__(self, session: AsyncSession, user_context: UserContext | None = None):
        self.session = session
        self.user_context = user_context
        self.model_class = RegistryItem

    async def get_by_id(self, id: UUID | str) -> RegistryItem | None:
        return await self.session.get(RegistryItem, id)

    async def list_all(
        self, limit: int | None = None, offset: int | None = None, **filters: Any
    ) -> list[RegistryItem]:
        query = select(RegistryItem)
        for field, value in filters.items():
            if hasattr(RegistryItem, field):
                query = query.where(getattr(RegistryItem, field) == value)
        query = query.order_by(RegistryItem.created_at.desc())
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def list_by_registry(
        self,
        registry_id: UUID | str,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[RegistryItem]:
        # Alphabetical by name, case-insensitive (so "monday.com"/"v0.dev" sort
        # naturally, not after "Zapier"). Ordering precedes pagination so the
        # catalog is consistently A→Z across pages / infinite scroll.
        query = (
            select(RegistryItem)
            .where(RegistryItem.registry_id == registry_id)
            .order_by(func.lower(RegistryItem.name))
        )
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create(self, **kwargs: Any) -> RegistryItem:
        record = RegistryItem(**kwargs)
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def update(self, id: UUID | str, **kwargs: Any) -> RegistryItem | None:
        record = await self.session.get(RegistryItem, id)
        if record is None:
            return None
        for field, value in kwargs.items():
            if hasattr(record, field):
                setattr(record, field, value)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def delete(self, id: UUID | str) -> bool:
        record = await self.session.get(RegistryItem, id)
        if record is None:
            return False
        await self.session.delete(record)
        await self.session.commit()
        return True

    async def get_by_external_id(
        self,
        registry_id: UUID | str,
        external_id: str,
    ) -> RegistryItem | None:
        """Find a catalog item by its external ID within a registry."""
        query = (
            select(RegistryItem)
            .where(RegistryItem.registry_id == registry_id)
            .where(RegistryItem.external_id == external_id)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    # ── Browsing (the /explore gallery) ──
    #
    # One ordered query across every active registry of a type. Paging each
    # registry separately and stitching the results client-side cannot work: a
    # single offset has no meaning over the concatenation, so pages past the
    # first skip whole slices of each registry. Filtering and sorting live here
    # for the same reason -- doing them on the loaded prefix reorders the list
    # under the user as more pages arrive, and hides matches that were never
    # fetched.

    def _browse_filter(
        self, registry_type: str, q: str | None, category: str | None
    ) -> list[ColumnElement[bool]]:
        """WHERE clause shared by the page query, its total, and the facets."""
        conditions = [
            Registry.registry_type == registry_type,
            Registry.is_active.is_(True),
        ]
        if category:
            conditions.append(RegistryItem.category == category)
        if q:
            pattern = f"%{q}%"
            conditions.append(
                RegistryItem.name.ilike(pattern) | RegistryItem.description.ilike(pattern)
            )
        return conditions

    async def browse(
        self,
        registry_type: str,
        q: str | None = None,
        category: str | None = None,
        sort: str = DEFAULT_CATALOG_SORT,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RegistryItem], int]:
        """One page of a type's catalog, plus how many items match in total.

        The total is what lets the client know there is more to fetch even when
        the current page contributes nothing visible.
        """
        conditions = self._browse_filter(registry_type, q, category)
        join = select(RegistryItem).join(Registry, RegistryItem.registry_id == Registry.id)

        order_by = CATALOG_SORTS.get(sort, CATALOG_SORTS[DEFAULT_CATALOG_SORT])()
        page = join.where(*conditions).order_by(*order_by).offset(offset).limit(limit)
        items = list((await self.session.execute(page)).scalars().all())

        counted = (
            select(func.count())
            .select_from(RegistryItem)
            .join(Registry, RegistryItem.registry_id == Registry.id)
            .where(*conditions)
        )
        total = (await self.session.execute(counted)).scalar_one()
        return items, total

    async def category_counts(
        self, registry_type: str, q: str | None = None
    ) -> list[tuple[str, int]]:
        """Facet counts over the whole type, not just the loaded page.

        Deliberately ignores any active category filter -- the sidebar has to
        keep showing the other categories you could switch to. Uncategorised
        items are left out rather than collected into a bucket nothing selects.

        Ordered alphabetically, with the fallback bucket last. Ordering by size
        put each category wherever its count happened to land, so finding a
        known one meant reading the whole list -- and the counts are flat
        enough (most categories hold one or two entries) that size conveyed
        nothing to begin with.
        """
        conditions = self._browse_filter(registry_type, q, category=None)
        query = (
            select(RegistryItem.category, func.count().label("n"))
            .join(Registry, RegistryItem.registry_id == Registry.id)
            .where(*conditions, RegistryItem.category.is_not(None))
            .group_by(RegistryItem.category)
            .order_by(
                case((RegistryItem.category == FALLBACK_CATEGORY, 1), else_=0),
                RegistryItem.category.asc(),
            )
        )
        rows = (await self.session.execute(query)).all()
        return [(value, count) for value, count in rows]

    async def search(
        self,
        query_str: str | None = None,
        tag: str | None = None,
        update_available: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RegistryItem]:
        """Search catalog items across all registries (global catalog)."""
        query = select(RegistryItem)

        if update_available is not None:
            query = query.where(RegistryItem.update_available == update_available)
        if query_str:
            pattern = f"%{query_str}%"
            query = query.where(
                RegistryItem.name.ilike(pattern)
                | RegistryItem.description.ilike(pattern)
                | RegistryItem.external_id.ilike(pattern)
            )

        query = query.order_by(RegistryItem.name)
        if offset > 0:
            query = query.offset(offset)
        if limit > 0:
            query = query.limit(limit)

        result = await self.session.execute(query)
        items = list(result.scalars().all())

        if tag:
            items = [i for i in items if tag in (i.tags or [])]

        return items
