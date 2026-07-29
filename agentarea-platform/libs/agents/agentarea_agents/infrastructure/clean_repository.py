"""Compatibility repositories backed by the current infrastructure layer."""

from typing import Any

from agentarea_common.auth.context import UserContext
from agentarea_tasks.infrastructure.repository import TaskRepository as CurrentTaskRepository
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import Agent
from .repository import AgentRepository as CurrentAgentRepository


class AgentRepository(CurrentAgentRepository):
    """Compatibility alias for the current workspace-scoped agent repository."""

    async def find_active_agents(self, user_scoped: bool = False) -> list[Agent]:
        return await self.list_all(status="active")

    async def count_agents(self, user_scoped: bool = False, **filters: Any) -> int:
        return await self.count(**filters)


class TaskRepository(CurrentTaskRepository):
    """Compatibility alias for the current task repository."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, user_context)


class CustomAgentRepository(AgentRepository):
    """Small query helpers over AgentRepository."""

    async def find_agents_by_model(self, model_id: str, user_scoped: bool = False) -> list[Agent]:
        return await self.list_all(model_id=model_id)

    async def find_agents_with_planning(self, user_scoped: bool = False) -> list[Agent]:
        return await self.list_all(planning=True)
