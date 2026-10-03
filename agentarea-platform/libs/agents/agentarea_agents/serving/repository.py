from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_agents.serving.models import AgentRevision


class AgentRevisionRepository(WorkspaceScopedRepository[AgentRevision]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, AgentRevision, user_context)

    async def get_for_agent(self, agent_id: UUID, revision_id: UUID) -> AgentRevision | None:
        result = await self.session.execute(
            select(AgentRevision).where(
                AgentRevision.id == revision_id,
                AgentRevision.agent_id == agent_id,
                self._get_workspace_filter(),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_agent(self, agent_id: UUID) -> list[AgentRevision]:
        result = await self.session.execute(
            select(AgentRevision)
            .where(AgentRevision.agent_id == agent_id, self._get_workspace_filter())
            .order_by(AgentRevision.number.desc())
        )
        return list(result.scalars().all())

    async def next_number(self, agent_id: UUID) -> int:
        result = await self.session.execute(
            select(func.max(AgentRevision.number)).where(
                AgentRevision.agent_id == agent_id, self._get_workspace_filter()
            )
        )
        return (result.scalar_one_or_none() or 0) + 1
