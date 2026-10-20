"""Repository for OpenAPIConnection CRUD operations."""

from typing import Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from agentarea_common.constants import MANAGED_BY_PLATFORM
from sqlalchemy import column, func, or_, select, table, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_openapi.domain.models import OpenAPIConnection


class OpenAPIConnectionRepository(WorkspaceScopedRepository[OpenAPIConnection]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, OpenAPIConnection, user_context)

    def _get_workspace_filter(self):
        """The workspace's own connections, plus the platform-managed ones.

        As for MCP instances: a connection the platform supplies lives in the platform
        workspace, which no tenant can name. Writes re-assert the strict filter, so a
        tenant can call the platform's connection but never edit or delete it.
        """
        return or_(
            self._strict_workspace_filter(),
            OpenAPIConnection.managed_by == MANAGED_BY_PLATFORM,
        )

    def _strict_workspace_filter(self):
        return super()._get_workspace_filter()

    async def update(self, id, creator_scoped: bool = False, **kwargs):
        return await self._scoped_write(super().update, id, creator_scoped=creator_scoped, **kwargs)

    async def delete(self, id, creator_scoped: bool = False) -> bool:
        return bool(await self._scoped_write(super().delete, id, creator_scoped=creator_scoped))

    async def _scoped_write(self, op, id, **kwargs):
        owned = await self.session.execute(
            select(OpenAPIConnection.id).where(
                OpenAPIConnection.id == id, self._strict_workspace_filter()
            )
        )
        if owned.scalar_one_or_none() is None:
            return None
        return await op(id, **kwargs)

    async def list_connections(
        self,
        status: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[OpenAPIConnection], int]:
        query = select(self.model_class).where(self._get_workspace_filter())

        if status:
            query = query.where(self.model_class.status == status)
        if search:
            pattern = f"%{search}%"
            query = query.where(
                or_(
                    self.model_class.name.ilike(pattern),
                    self.model_class.description.ilike(pattern),
                )
            )

        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.session.execute(count_query)).scalar_one()

        query = query.order_by(self.model_class.created_at.desc())
        if offset > 0:
            query = query.offset(offset)
        if limit > 0:
            query = query.limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().all()), total

    async def catalog_id(self, registry_item_id: UUID) -> str | None:
        """The catalog id of the registry item a connection was made from."""
        items = table("registry_items", column("id"), column("external_id"))
        return await self.session.scalar(
            select(items.c.external_id).where(items.c.id == registry_item_id)
        )

    async def catalog_spec_content(self, registry_item_id: UUID) -> dict[str, Any] | None:
        """The OpenAPI spec the registry item a connection was made from carries inline."""
        items = table("registry_items", column("id"), column("spec"))
        spec = await self.session.scalar(select(items.c.spec).where(items.c.id == registry_item_id))
        content = spec.get("spec_content") if isinstance(spec, dict) else None
        return content if isinstance(content, dict) else None

    async def record_dispatch(self, connection_id: UUID, dispatch: dict[str, Any]) -> None:
        """Write ``last_dispatch`` alone; a call is not an edit, so ``updated_at`` stays.

        Runs in a savepoint: a failed write must leave the caller's transaction,
        which still has the call's own work to commit, usable.
        """
        async with self.session.begin_nested():
            await self.session.execute(
                update(self.model_class)
                .where(self.model_class.id == connection_id, self._strict_workspace_filter())
                .values(last_dispatch=dispatch, updated_at=self.model_class.updated_at)
            )
