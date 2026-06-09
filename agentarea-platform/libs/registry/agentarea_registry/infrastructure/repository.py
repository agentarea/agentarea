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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_registry.domain.models import Registry, RegistryItem


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
        return await self.list_all(limit=limit, offset=offset, registry_id=registry_id)

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
