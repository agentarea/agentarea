"""Repository for WorkspaceSettings."""

import logging

from agentarea_common.auth.context import UserContext
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_workspaces.domain.models import WorkspaceSettings

logger = logging.getLogger(__name__)


class WorkspaceSettingsRepository:
    """Repository for per-workspace configuration.

    Not workspace-scoped in the same way as resources — there is one row
    per workspace, keyed by workspace_id. Reads/writes are constrained to
    the caller's current workspace via UserContext.
    """

    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.user_context = user_context

    async def get(self) -> WorkspaceSettings | None:
        """Fetch settings for the current workspace, or None if never saved."""
        query = select(WorkspaceSettings).where(
            WorkspaceSettings.workspace_id == self.user_context.workspace_id
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def upsert(self, monthly_cap_usd: float | None) -> WorkspaceSettings:
        """Insert or update the row for the current workspace.

        Race-safe via INSERT ... ON CONFLICT DO UPDATE on workspace_id.
        """
        workspace_id = self.user_context.workspace_id
        stmt = (
            pg_insert(WorkspaceSettings)
            .values(workspace_id=workspace_id, monthly_cap_usd=monthly_cap_usd)
            .on_conflict_do_update(
                index_elements=["workspace_id"],
                set_={"monthly_cap_usd": monthly_cap_usd},
            )
            .returning(WorkspaceSettings)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one()
