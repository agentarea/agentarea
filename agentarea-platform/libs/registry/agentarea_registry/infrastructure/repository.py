"""Repositories for Registry and RegistryItem domain models.

Registries and registry_items are catalog infrastructure (ADR-003), not
WorkspaceScopedMixin rows: built-in content lives here once and is readable by
every tenant. A registry is either the platform's, seen by every workspace, or
one workspace's (ADR-0044). Sync and reconcile read every row; the catalog
reads a caller makes go through the ``visible`` methods, which keep another
workspace's registries and items out and need the caller's ``user_context``.
"""

from collections.abc import Collection
from typing import Any
from typing import cast as type_cast
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import unscoped
from sqlalchemy import (
    String,
    case,
    cast,
    column,
    delete,
    exists,
    false,
    func,
    or_,
    select,
    table,
    text,
    update,
)
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from agentarea_registry.application.catalog_facets import (
    CATALOG_HOSTINGS,
    CATALOG_PRICINGS,
    CATALOG_PROTOCOLS,
    PROTOCOL_REGISTRY_TYPE,
)
from agentarea_registry.domain.models import Registry, RegistryItem, RegistryItemInstall

# Accepted catalog orderings, mapped to their ORDER BY. Every ordering ends with
# ``id`` so rows with equal keys can't let OFFSET paging repeat one and drop
# another. Public: the API validates ``sort`` against these names rather than
# silently ignoring an unknown one, and the webapp mirrors them in SORT_KEYS.
#
# ``recommended`` is the catalog's own curation, not a popularity metric:
# hand-featured entries first, then whole sources by weight (a curated system
# catalog outranks an opt-in bulk mirror), then each source's published order
# (GitHub-star order for skills, official-integrations-first for connections).
# ``sort_key`` before ``id`` keeps equal ranks alphabetical rather than random.
CATALOG_SORTS: dict[str, Any] = {
    "recommended": lambda: (
        RegistryItem.featured.desc(),
        RegistryItem.registry_priority.asc(),
        RegistryItem.recommendation_rank.asc(),
        RegistryItem.sort_key.asc(),
        RegistryItem.id.asc(),
    ),
    "name": lambda: (RegistryItem.sort_key.asc(), RegistryItem.id.asc()),
}
DEFAULT_CATALOG_SORT = "recommended"

# The category sources fall back to when they can't classify an entry. It is a
# bucket, not a peer category, so the facet list sorts it last rather than
# letting it land mid-alphabet or -- as ordering by size did -- near the top.
#
# Matched case-insensitively because the sources disagree on spelling: skills
# write "other", the MCP catalog title-cases its agentarea:category values and
# writes "Other". Comparing exactly demoted only one of them.
FALLBACK_CATEGORY = "other"

# Registry columns copied onto each of its items, as registry field -> item field.
_COPIED_REGISTRY_FIELDS = {
    "registry_type": "registry_type",
    "recommendation_priority": "registry_priority",
    "is_active": "registry_active",
    "workspace_id": "registry_workspace_id",
    "trust": "registry_trust",
}


def _caller_workspace(user_context: UserContext | None) -> str:
    """The workspace a catalog read is for; there is no default to fall back to."""
    if user_context is None or not user_context.workspace_id:
        raise ValueError("a catalog read needs the caller's workspace")
    return user_context.workspace_id


def visible_registry(workspace_id: str) -> ColumnElement[bool]:
    return or_(Registry.workspace_id.is_(None), Registry.workspace_id == workspace_id)


def visible_item(workspace_id: str) -> ColumnElement[bool]:
    """The platform's items and the caller's workspace's, never another's."""
    return or_(
        RegistryItem.registry_workspace_id.is_(None),
        RegistryItem.registry_workspace_id == workspace_id,
    )


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

    async def list_visible(
        self,
        active_only: bool = False,
        registry_type: str | None = None,
        scope: str | None = None,
    ) -> list[Registry]:
        """The platform's registries and the caller's workspace's."""
        query = select(Registry).where(visible_registry(_caller_workspace(self.user_context)))
        if active_only:
            query = query.where(Registry.is_active.is_(True))
        if registry_type:
            query = query.where(Registry.registry_type == registry_type)
        if scope:
            query = query.where(Registry.scope == scope)
        result = await self.session.execute(query.order_by(Registry.created_at.desc()))
        return list(result.scalars().all())

    async def get_visible(self, id: UUID | str) -> Registry | None:
        record = await self.session.get(Registry, id)
        if record is None or record.workspace_id not in (
            None,
            _caller_workspace(self.user_context),
        ):
            return None
        return record

    async def get_many(self, ids: set[str]) -> list[Registry]:
        if not ids:
            return []
        result = await self.session.execute(select(Registry).where(Registry.id.in_(ids)))
        return list(result.scalars().all())

    async def get_platform_by_name(self, name: str) -> Registry | None:
        result = await self.session.execute(
            select(Registry).where(Registry.scope == "platform", Registry.name == name)
        )
        return result.scalar_one_or_none()

    async def list_active_workspace_registries(self) -> list[Registry]:
        """Every workspace's active synchronized registries, for reconcile."""
        result = await self.session.execute(
            select(Registry)
            .where(
                Registry.scope == "workspace",
                Registry.is_active.is_(True),
                Registry.source_type != "managed",
            )
            .order_by(Registry.workspace_id, Registry.name)
        )
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
        copied = {
            item_field: kwargs[field]
            for field, item_field in _COPIED_REGISTRY_FIELDS.items()
            if field in kwargs
        }
        if "registry_active" in copied:
            # An item its source dropped stays hidden when the registry is
            # switched back on.
            copied["registry_active"] = (
                RegistryItem.in_source if copied["registry_active"] else false()
            )
        if copied:
            await self.session.execute(
                update(RegistryItem).where(RegistryItem.registry_id == id).values(**copied)
            )
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

    async def get_visible(self, id: UUID | str) -> RegistryItem | None:
        """The item, unless it belongs to another workspace's registry."""
        record = await self.session.get(RegistryItem, id)
        if record is None or record.registry_workspace_id not in (
            None,
            _caller_workspace(self.user_context),
        ):
            return None
        return record

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

    async def count_by_registry(self, registry_id: UUID | str) -> int:
        """Return the exact number of catalog items owned by a registry."""
        query = (
            select(func.count())
            .select_from(RegistryItem)
            .where(RegistryItem.registry_id == registry_id)
        )
        return (await self.session.execute(query)).scalar_one()

    async def create(self, **kwargs: Any) -> RegistryItem:
        registry = await self.session.get(Registry, kwargs["registry_id"])
        if registry is None:
            raise ValueError(f"Registry {kwargs['registry_id']} not found")
        record = RegistryItem(
            **kwargs,
            **{
                item_field: getattr(registry, field)
                for field, item_field in _COPIED_REGISTRY_FIELDS.items()
            },
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def mark_in_source(self, registry_id: UUID | str, external_ids: set[str]) -> int:
        """Record which of a registry's items its source still publishes.

        Items the source dropped leave the catalog (``registry_active`` false)
        without being deleted; one that comes back returns. Returns how many
        items are now out of the source.
        """
        registry = await self.session.get(Registry, registry_id)
        if registry is None:
            raise ValueError(f"Registry {registry_id} not found")
        present = RegistryItem.external_id.in_(external_ids) if external_ids else false()
        active = present if registry.is_active else false()
        await self.session.execute(
            update(RegistryItem)
            .where(
                RegistryItem.registry_id == registry_id,
                or_(
                    RegistryItem.in_source.is_distinct_from(present),
                    RegistryItem.registry_active.is_distinct_from(active),
                ),
            )
            .values(in_source=present, registry_active=active)
        )
        await self.session.commit()
        return (
            await self.session.execute(
                select(func.count()).where(
                    RegistryItem.registry_id == registry_id, RegistryItem.in_source.is_(False)
                )
            )
        ).scalar_one()

    async def move_references(
        self, registry_id: UUID | str, replacements: Collection[UUID | str]
    ) -> int:
        """Point every use of the registry's items at the same item of a replacement.

        "The same item" is the one with the same ``external_id`` that a
        replacement registry still publishes (the first by registry weight).
        Installs, forks, agents and connections move, in every workspace, except
        where a workspace already holds the replacement item: one fork and one
        install per item and workspace. Not committed, so the caller deletes
        what is left unused in the same transaction. Returns how many moved.
        """
        if not replacements:
            return 0
        # Raw SQL over other modules' tables, across every workspace: the
        # tenant scope does not confine it, and must not.
        result = await self.session.execute(
            text(
                """
                WITH moves AS (
                    SELECT DISTINCT ON (old.id) old.id AS old_id, new.id AS new_id
                    FROM registry_items old
                    JOIN registry_items new
                      ON new.external_id = old.external_id
                     AND new.registry_type = old.registry_type
                    WHERE old.registry_id = :registry_id
                      AND new.registry_id = ANY(:replacements)
                      AND new.in_source
                    ORDER BY old.id, new.registry_priority, new.registry_id
                ),
                forks AS (
                    UPDATE skills s SET registry_item_id = m.new_id
                    FROM moves m
                    WHERE s.registry_item_id = m.old_id
                      AND NOT EXISTS (
                          SELECT 1 FROM skills other
                          WHERE other.workspace_id = s.workspace_id
                            AND other.registry_item_id = m.new_id
                      )
                    RETURNING 1
                ),
                installs AS (
                    UPDATE registry_item_installs x SET registry_item_id = m.new_id
                    FROM moves m
                    WHERE x.registry_item_id = m.old_id
                      AND NOT EXISTS (
                          SELECT 1 FROM registry_item_installs other
                          WHERE other.workspace_id = x.workspace_id
                            AND other.registry_item_id = m.new_id
                      )
                    RETURNING 1
                ),
                agents_moved AS (
                    UPDATE agents a SET registry_item_id = m.new_id::text
                    FROM moves m WHERE a.registry_item_id = m.old_id::text
                    RETURNING 1
                ),
                servers AS (
                    UPDATE mcp_servers t SET registry_item_id = m.new_id
                    FROM moves m WHERE t.registry_item_id = m.old_id
                    RETURNING 1
                ),
                connections AS (
                    UPDATE openapi_connections t SET registry_item_id = m.new_id
                    FROM moves m WHERE t.registry_item_id = m.old_id
                    RETURNING 1
                )
                SELECT (SELECT count(*) FROM forks) + (SELECT count(*) FROM installs)
                     + (SELECT count(*) FROM agents_moved) + (SELECT count(*) FROM servers)
                     + (SELECT count(*) FROM connections)
                """
            ),
            {
                "registry_id": UUID(str(registry_id)),
                "replacements": [UUID(str(r)) for r in replacements],
            },
        )
        return int(result.scalar_one())

    async def delete_unreferenced_out_of_source(self, registry_id: UUID | str) -> int:
        """Delete the registry's items its source dropped that nothing uses.

        An item stays while a workspace installed, forked or connected to it,
        or while the platform materialized it (an MCP mirror, a model spec);
        what stays carries its registry's trust, which the migration that
        added the column gave only to items still in the source. Returns how
        many items were deleted.
        """
        registry = await self.session.get(Registry, registry_id)
        if registry is None:
            raise ValueError(f"Registry {registry_id} not found")
        uuid_refs = [
            table(name, column("registry_item_id"))
            for name in ("skills", "mcp_servers", "openapi_connections")
        ]
        agents = table("agents", column("registry_item_id"))
        referenced = or_(
            RegistryItem.installed_entity_id.is_not(None),
            exists().where(RegistryItemInstall.registry_item_id == RegistryItem.id),
            *(exists().where(ref.c.registry_item_id == RegistryItem.id) for ref in uuid_refs),
            exists().where(agents.c.registry_item_id == cast(RegistryItem.id, String)),
        )
        # Core tables, not ORM entities: under a workspace scope an entity's
        # EXISTS would see only that workspace and delete what others use.
        with unscoped("an item is referenced from any workspace; the check must see all of them"):
            result = await self.session.execute(
                delete(RegistryItem).where(
                    RegistryItem.registry_id == registry_id,
                    RegistryItem.in_source.is_(False),
                    ~referenced,
                )
            )
        await self.session.execute(
            update(RegistryItem)
            .where(
                RegistryItem.registry_id == registry_id,
                RegistryItem.in_source.is_(False),
                RegistryItem.registry_trust.is_distinct_from(registry.trust),
            )
            .values(registry_trust=registry.trust)
        )
        await self.session.commit()
        return type_cast(CursorResult[Any], result).rowcount

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

    async def next_recommendation_rank(self, registry_id: UUID | str) -> int:
        """Rank that places a new item after everything already in a registry.

        Managed registries have no source order to read a position from, so a
        published item lands at the end instead of tying with -- and silently
        outranking, via the alphabetical tiebreak -- the existing catalog.
        """
        highest = (
            await self.session.execute(
                select(func.max(RegistryItem.recommendation_rank)).where(
                    RegistryItem.registry_id == registry_id
                )
            )
        ).scalar()
        return 0 if highest is None else highest + 1

    # ── Browsing (the /explore gallery) ──
    #
    # One ordered query across every active registry of a type. Paging each
    # registry separately and stitching the results client-side cannot work: a
    # single offset has no meaning over the concatenation, so pages past the
    # first skip whole slices of each registry. Filtering and sorting live here
    # for the same reason -- doing them on the loaded prefix reorders the list
    # under the user as more pages arrive, and hides matches that were never
    # fetched.
    #
    # None of these join `registries`: type, weight and active flag are read
    # from the item's own copies, which keeps every query on one table, where
    # the browse indexes on RegistryItem can serve it.

    def _browse_filter(
        self,
        registry_type: str,
        q: str | None,
        category: str | None,
        protocol: str | None = None,
        hosting: str | None = None,
        pricing: str | None = None,
    ) -> list[ColumnElement[bool]]:
        """WHERE clause shared by the page query, its total, and the facets."""
        conditions: list[ColumnElement[bool]] = [
            RegistryItem.registry_type == registry_type,
            # Bare column, not `IS TRUE`: it has to match the partial indexes'
            # predicate for the planner to use them.
            RegistryItem.registry_active.expression,
            visible_item(_caller_workspace(self.user_context)),
        ]
        if category:
            conditions.append(RegistryItem.category == category)
        if protocol:
            conditions.append(RegistryItem.protocol == protocol)
        if hosting:
            conditions.append(RegistryItem.hosting == hosting)
        if pricing:
            conditions.append(RegistryItem.pricing == pricing)
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
        protocol: str | None = None,
        hosting: str | None = None,
        pricing: str | None = None,
        sort: str = DEFAULT_CATALOG_SORT,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RegistryItem], int]:
        """One page of a type's catalog, plus how many items match in total.

        The total is what lets the client know there is more to fetch even when
        the current page contributes nothing visible.
        """
        conditions = self._browse_filter(registry_type, q, category, protocol, hosting, pricing)
        order_by = CATALOG_SORTS.get(sort, CATALOG_SORTS[DEFAULT_CATALOG_SORT])()
        page = (
            select(RegistryItem).where(*conditions).order_by(*order_by).offset(offset).limit(limit)
        )
        items = list((await self.session.execute(page)).scalars().all())

        counted = select(func.count()).select_from(RegistryItem).where(*conditions)
        total = (await self.session.execute(counted)).scalar_one()
        return items, total

    async def category_counts(
        self,
        registry_type: str,
        q: str | None = None,
        protocol: str | None = None,
        hosting: str | None = None,
        pricing: str | None = None,
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
        conditions = self._browse_filter(
            registry_type, q, category=None, protocol=protocol, hosting=hosting, pricing=pricing
        )
        query = (
            select(RegistryItem.category, func.count().label("n"))
            .where(*conditions, RegistryItem.category.is_not(None))
            .group_by(RegistryItem.category)
            .order_by(
                case((func.lower(RegistryItem.category) == FALLBACK_CATEGORY, 1), else_=0),
                RegistryItem.category.asc(),
            )
        )
        rows = (await self.session.execute(query)).all()
        return [(value, count) for value, count in rows]

    async def protocol_counts(
        self,
        registry_type: str,
        q: str | None = None,
        category: str | None = None,
        hosting: str | None = None,
        pricing: str | None = None,
    ) -> list[tuple[str, int]]:
        """How the matching connections split between MCP servers and HTTP APIs.

        Empty for every other registry type: "protocol" is only a question the
        connections catalog can answer. Like the category facet, this ignores
        the active protocol so the other side stays reachable, and drops an
        empty side rather than offering a filter that returns nothing.
        """
        if registry_type != PROTOCOL_REGISTRY_TYPE:
            return []
        conditions = self._browse_filter(
            registry_type, q, category, protocol=None, hosting=hosting, pricing=pricing
        )
        query = (
            select(RegistryItem.protocol, func.count())
            .where(*conditions)
            .group_by(RegistryItem.protocol)
        )
        # .tuples() so the pairs arrive typed: over raw Rows the key type is
        # lost and the dict reads as bytes.
        counts: dict[str | None, int] = dict((await self.session.execute(query)).tuples().all())
        return [(name, counts[name]) for name in CATALOG_PROTOCOLS if counts.get(name)]

    async def hosting_counts(
        self,
        registry_type: str,
        q: str | None = None,
        category: str | None = None,
        protocol: str | None = None,
        pricing: str | None = None,
    ) -> list[tuple[str, int]]:
        """How the matching MCP connections split between vendor-hosted and run here.

        Connections catalog only. Ignores the active hosting filter so the other
        side stays reachable, and drops an empty side.
        """
        if registry_type != PROTOCOL_REGISTRY_TYPE:
            return []
        conditions = self._browse_filter(
            registry_type, q, category, protocol, hosting=None, pricing=pricing
        )
        query = (
            select(RegistryItem.hosting, func.count())
            .where(*conditions)
            .group_by(RegistryItem.hosting)
        )
        counts: dict[str | None, int] = dict((await self.session.execute(query)).tuples().all())
        return [(name, counts[name]) for name in CATALOG_HOSTINGS if counts.get(name)]

    async def pricing_counts(
        self,
        registry_type: str,
        q: str | None = None,
        category: str | None = None,
        protocol: str | None = None,
        hosting: str | None = None,
    ) -> list[tuple[str, int]]:
        """How the matching connections split between paid, own-key and free.

        Connections catalog only. Ignores the active pricing filter so the other
        sides stay reachable, and drops an empty side.
        """
        if registry_type != PROTOCOL_REGISTRY_TYPE:
            return []
        conditions = self._browse_filter(registry_type, q, category, protocol, hosting)
        query = (
            select(RegistryItem.pricing, func.count())
            .where(*conditions)
            .group_by(RegistryItem.pricing)
        )
        counts: dict[str | None, int] = dict((await self.session.execute(query)).tuples().all())
        return [(name, counts[name]) for name in CATALOG_PRICINGS if counts.get(name)]

    async def search(
        self,
        query_str: str | None = None,
        tag: str | None = None,
        update_available: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RegistryItem]:
        """Search the catalog items the caller's workspace may see."""
        query = select(RegistryItem).where(visible_item(_caller_workspace(self.user_context)))

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
