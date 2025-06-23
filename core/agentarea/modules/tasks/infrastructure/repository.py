"""Task repository for AgentArea platform.

This module provides repository implementations for task persistence and retrieval
operations, following domain-driven design principles.
"""

import builtins
import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea.common.base.repository import BaseRepository
from agentarea.modules.tasks.domain.models import Task, TaskState

logger = logging.getLogger(__name__)


class TaskRepositoryInterface(ABC):
    """Interface for task repository operations."""

    @abstractmethod
    async def get_by_id(self, task_id: str) -> Task | None:
        """Get a task by its ID."""
        pass

    @abstractmethod
    async def get_by_user_id(self, user_id: str, limit: int = 100, offset: int = 0) -> list[Task]:
        """Get tasks created by a specific user."""
        pass

    @abstractmethod
    async def get_by_agent_id(
        self, agent_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[Task]:
        """Get tasks assigned to a specific agent."""
        pass

    @abstractmethod
    async def create(self, task: Task) -> Task:
        """Create a new task."""
        pass

    @abstractmethod
    async def update(self, task: Task) -> Task:
        """Update an existing task."""
        pass

    @abstractmethod
    async def delete(self, task_id: str) -> bool:
        """Delete a task by its ID."""
        pass

    @abstractmethod
    async def get_pending_tasks(self, limit: int = 20) -> list[Task]:
        """Get pending tasks that need to be assigned to agents."""
        pass

    @abstractmethod
    async def get_tasks_by_status(
        self, status: TaskState, limit: int = 100, offset: int = 0
    ) -> list[Task]:
        """Get tasks by their status."""
        pass


class SQLAlchemyTaskRepository(BaseRepository[Task], TaskRepositoryInterface):
    """SQLAlchemy implementation of the task repository."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # Implementation of BaseRepository abstract methods
    async def get(self, task_id: UUID) -> Task | None:
        """Get a task by its UUID ID (implementing BaseRepository interface)."""
        return await self.get_by_id(str(task_id))

    async def list(self) -> list[Task]:
        """List all tasks (implementing BaseRepository interface)."""
        try:
            stmt = select(Task).order_by(Task.id.desc())
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error listing all tasks: {e}")
            return []

    async def get_by_id(self, task_id: str) -> Task | None:
        """Get a task by its ID."""
        try:
            stmt = select(Task).where(Task.id == task_id)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error retrieving task by ID {task_id}: {e}")
            return None

    async def get_by_user_id(self, user_id: str, limit: int = 100, offset: int = 0) -> builtins.list[Task]:
        """Get tasks created by a specific user."""
        try:
            stmt = (
                select(Task)
                .where(Task.created_by == user_id)
                .order_by(desc(Task.created_at))
                .limit(limit)
                .offset(offset)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error retrieving tasks for user {user_id}: {e}")
            return []

    async def get_by_agent_id(
        self, agent_id: UUID, limit: int = 100, offset: int = 0
    ) -> builtins.list[Task]:
        """Get tasks assigned to a specific agent."""
        try:
            stmt = (
                select(Task)
                .where(Task.assigned_agent_id == agent_id)
                .order_by(desc(Task.created_at))
                .limit(limit)
                .offset(offset)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error retrieving tasks for agent {agent_id}: {e}")
            return []

    async def create(self, task: Task) -> Task:
        """Create a new task."""
        try:
            self.session.add(task)
            await self.session.flush()
            await self.session.refresh(task)
            return task
        except Exception as e:
            logger.error(f"Error creating task: {e}")
            raise

    async def update(self, task: Task) -> Task:
        """Update an existing task."""
        try:
            task.updated_at = datetime.now(UTC)
            self.session.add(task)
            await self.session.flush()
            await self.session.refresh(task)
            return task
        except Exception as e:
            logger.error(f"Error updating task {task.id}: {e}")
            raise

    async def delete(self, task_id: str) -> bool:
        """Delete a task by its ID."""
        try:
            task = await self.get_by_id(task_id)
            if task:
                await self.session.delete(task)
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting task {task_id}: {e}")
            return False

    async def get_pending_tasks(self, limit: int = 20) -> builtins.list[Task]:
        """Get pending tasks that need to be assigned to agents."""
        try:
            stmt = (
                select(Task)
                .where(
                    and_(Task.status.state == TaskState.SUBMITTED, Task.assigned_agent_id.is_(None))
                )
                .order_by(desc(Task.priority), Task.created_at)
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error retrieving pending tasks: {e}")
            return []

    async def get_tasks_by_status(
        self, status: TaskState, limit: int = 100, offset: int = 0
    ) -> builtins.list[Task]:
        """Get tasks by their status."""
        try:
            stmt = (
                select(Task)
                .where(Task.status.state == status)
                .order_by(desc(Task.created_at))
                .limit(limit)
                .offset(offset)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error retrieving tasks by status {status}: {e}")
            return []

    async def get_tasks_by_collaboration(
        self, agent_id: UUID, limit: int = 100, offset: int = 0
    ) -> builtins.list[Task]:
        """Get tasks where the agent is a collaborator but not the primary assignee."""
        try:
            # This is a more complex query that would need to check the collaboration field
            # which contains a list of collaborating agents
            # Note: This is a simplified implementation and may need adjustment based on actual data structure
            stmt = (
                select(Task)
                .where(
                    and_(
                        Task.assigned_agent_id != agent_id,  # Not the primary assignee
                        Task.collaboration.has(collaborating_agents=agent_id),  # Is a collaborator
                    )
                )
                .order_by(desc(Task.created_at))
                .limit(limit)
                .offset(offset)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error retrieving collaboration tasks for agent {agent_id}: {e}")
            return []

    async def get_tasks_by_organization(
        self, organization_id: str, limit: int = 100, offset: int = 0
    ) -> builtins.list[Task]:
        """Get tasks for a specific organization."""
        try:
            stmt = (
                select(Task)
                .where(Task.organization_id == organization_id)
                .order_by(desc(Task.created_at))
                .limit(limit)
                .offset(offset)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error retrieving tasks for organization {organization_id}: {e}")
            return []

    async def get_tasks_by_workspace(
        self, workspace_id: str, limit: int = 100, offset: int = 0
    ) -> builtins.list[Task]:
        """Get tasks for a specific workspace."""
        try:
            stmt = (
                select(Task)
                .where(Task.workspace_id == workspace_id)
                .order_by(desc(Task.created_at))
                .limit(limit)
                .offset(offset)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(f"Error retrieving tasks for workspace {workspace_id}: {e}")
            return []
