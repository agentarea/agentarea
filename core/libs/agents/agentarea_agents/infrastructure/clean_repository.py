"""Clean agent repository using the new composable approach."""

from typing import Optional

from agentarea_common.auth.context import UserContext
from agentarea_common.base.repository import (
    ContextualRepository,
    FieldFilter,
    Repository,
    SoftDeleteOperations,
)
from agentarea_tasks.infrastructure.models import TaskORM
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import Agent


class AgentRepository:
    """Agent repository using composition instead of inheritance."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.user_context = user_context
        self.contextual_repo = ContextualRepository(session, user_context)

    def _get_repo(self, user_scoped: bool = False) -> Repository[Agent]:
        """Get repository with appropriate filters."""
        if user_scoped:
            return self.contextual_repo.for_model_with_user_scope(Agent)
        return self.contextual_repo.for_model(Agent)

    async def get_by_id(self, agent_id: str, user_scoped: bool = False) -> Agent | None:
        """Get agent by ID."""
        repo = self._get_repo(user_scoped)
        return await repo.get_by_id(agent_id)

    async def list_all(self, user_scoped: bool = False, **filters) -> list[Agent]:
        """List all agents."""
        repo = self._get_repo(user_scoped)
        return await repo.list_all(**filters)

    async def find_active_agents(self, user_scoped: bool = False) -> list[Agent]:
        """Find all active agents."""
        repo = self._get_repo(user_scoped)
        return await repo.list_all(status="active")

    async def get_agent_by_name(self, name: str, user_scoped: bool = False) -> Agent | None:
        """Get agent by name."""
        repo = self._get_repo(user_scoped)
        agents = await repo.list_all(name=name)
        return agents[0] if agents else None

    async def create_agent(self, name: str, **kwargs) -> Agent:
        """Create a new agent."""
        # Create record with context
        agent = self.contextual_repo.create_with_context(Agent, name=name, **kwargs)

        self.session.add(agent)
        await self.session.commit()
        await self.session.refresh(agent)
        return agent

    async def update_agent(
        self, agent_id: str, user_scoped: bool = False, **kwargs
    ) -> Agent | None:
        """Update an agent."""
        repo = self._get_repo(user_scoped)
        return await repo.update(agent_id, **kwargs)

    async def delete_agent(self, agent_id: str, user_scoped: bool = False) -> bool:
        """Delete an agent."""
        repo = self._get_repo(user_scoped)
        return await repo.delete(agent_id)

    async def count_agents(self, user_scoped: bool = False, **filters) -> int:
        """Count agents."""
        repo = self._get_repo(user_scoped)
        return await repo.count(**filters)


class TaskRepository:
    """Task repository with soft delete support."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.user_context = user_context
        self.contextual_repo = ContextualRepository(session, user_context)

    def _get_repo(self, user_scoped: bool = False) -> Repository:
        """Get repository with appropriate filters."""
        if user_scoped:
            return self.contextual_repo.for_model_with_user_scope(TaskORM)
        return self.contextual_repo.for_model(TaskORM)

    def _get_soft_delete_ops(self, user_scoped: bool = False) -> SoftDeleteOperations:
        """Get soft delete operations."""
        repo = self._get_repo(user_scoped)
        return SoftDeleteOperations(repo)

    async def get_by_id(self, task_id: str, user_scoped: bool = False) -> Optional:
        """Get task by ID."""
        repo = self._get_repo(user_scoped)
        return await repo.get_by_id(task_id)

    async def list_all(
        self, user_scoped: bool = False, include_deleted: bool = False, **filters
    ) -> list:
        """List all tasks."""
        if include_deleted:
            # Remove soft delete filter to include deleted records
            from agentarea_common.base.repository import SoftDeleteFilter

            repo = self._get_repo(user_scoped)
            # Create new repo without soft delete filter
            filters_without_soft_delete = [
                f for f in repo._filters if not isinstance(f, SoftDeleteFilter)
            ]
            new_repo = Repository(repo.session, repo.model_class).with_filters(
                *filters_without_soft_delete
            )
            return await new_repo.list_all(**filters)

        repo = self._get_repo(user_scoped)
        return await repo.list_all(**filters)

    async def create_task(self, description: str, agent_id: str, **kwargs):
        """Create a new task."""
        from agentarea_tasks.infrastructure.orm import TaskORM

        # Create record with context
        task = self.contextual_repo.create_with_context(
            TaskORM, description=description, agent_id=agent_id, **kwargs
        )

        self.session.add(task)
        await self.session.commit()
        await self.session.refresh(task)
        return task

    async def soft_delete_task(self, task_id: str, user_scoped: bool = False) -> bool:
        """Soft delete a task."""
        ops = self._get_soft_delete_ops(user_scoped)
        return await ops.soft_delete(task_id)

    async def restore_task(self, task_id: str, user_scoped: bool = False) -> bool:
        """Restore a soft-deleted task."""
        ops = self._get_soft_delete_ops(user_scoped)
        return await ops.restore(task_id)

    async def list_deleted_tasks(self, user_scoped: bool = False) -> list:
        """List only soft-deleted tasks."""
        ops = self._get_soft_delete_ops(user_scoped)
        return await ops.list_deleted()


# Example of custom filtering
class CustomAgentRepository(AgentRepository):
    """Example of extending with custom filters."""

    async def find_agents_by_model(self, model_id: str, user_scoped: bool = False) -> list[Agent]:
        """Find agents using a specific model."""
        repo = self._get_repo(user_scoped)
        # Add custom filter
        model_filter = FieldFilter(model_id=model_id)
        custom_repo = repo.with_filters(model_filter)
        return await custom_repo.list_all()

    async def find_agents_with_planning(self, user_scoped: bool = False) -> list[Agent]:
        """Find agents with planning enabled."""
        repo = self._get_repo(user_scoped)
        planning_filter = FieldFilter(planning=True)
        custom_repo = repo.with_filters(planning_filter)
        return await custom_repo.list_all()
