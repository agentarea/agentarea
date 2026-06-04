"""Workspace-scoped repository for InstalledBundle."""

from __future__ import annotations

from agentarea_common.auth.context import UserContext
from agentarea_common.base import WorkspaceScopedRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_bundles.domain.models import InstalledBundle


class InstalledBundleRepository(WorkspaceScopedRepository[InstalledBundle]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, InstalledBundle, user_context)

    async def get_by_name(self, name: str) -> InstalledBundle | None:
        """Find an imported package by name within the current workspace."""
        query = select(self.model_class).where(
            self.model_class.name == name,
            self._get_workspace_filter(),
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
