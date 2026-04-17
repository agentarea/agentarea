"""Repositories for Registry and RegistryItem domain models."""

from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_registry.domain.models import Registry, RegistryItem


class RegistryRepository(WorkspaceScopedRepository[Registry]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, Registry, user_context)

    async def list_active(self, registry_type: str | None = None) -> list[Registry]:
        filters: dict = {"is_active": True}
        if registry_type:
            filters["registry_type"] = registry_type
        return await self.list_all(**filters)


class RegistryItemRepository(WorkspaceScopedRepository[RegistryItem]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, RegistryItem, user_context)

    async def list_by_registry(
        self,
        registry_id: UUID | str,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[RegistryItem]:
        return await self.list_all(limit=limit, offset=offset, registry_id=registry_id)

    async def get_by_external_id(
        self,
        registry_id: UUID | str,
        external_id: str,
    ) -> RegistryItem | None:
        """Find a catalog item by its external ID within a registry."""
        query = (
            select(self.model_class)
            .where(self._get_workspace_filter())
            .where(self.model_class.registry_id == registry_id)
            .where(self.model_class.external_id == external_id)
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
        """Search catalog items across all registries in the workspace."""
        query = select(self.model_class).where(self._get_workspace_filter())

        if update_available is not None:
            query = query.where(self.model_class.update_available == update_available)
        if query_str:
            pattern = f"%{query_str}%"
            query = query.where(
                self.model_class.name.ilike(pattern)
                | self.model_class.description.ilike(pattern)
                | self.model_class.external_id.ilike(pattern)
            )

        query = query.order_by(self.model_class.name)
        if offset > 0:
            query = query.offset(offset)
        if limit > 0:
            query = query.limit(limit)

        result = await self.session.execute(query)
        items = list(result.scalars().all())

        if tag:
            items = [i for i in items if tag in (i.tags or [])]

        return items
