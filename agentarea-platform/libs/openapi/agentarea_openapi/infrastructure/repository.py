"""Repository for OpenAPIConnection CRUD operations."""

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_openapi.domain.models import OpenAPIConnection


class OpenAPIConnectionRepository(WorkspaceScopedRepository[OpenAPIConnection]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, OpenAPIConnection, user_context)

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
