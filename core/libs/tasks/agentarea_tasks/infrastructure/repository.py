"""Task repository for AgentArea platform.

This module provides repository implementations for task persistence and retrieval
operations, following domain-driven design principles.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from uuid import UUID

from agentarea_common.base.repository import BaseRepository
from agentarea_common.utils.types import TaskState
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_tasks.domain.models import Task as TaskDomain
from agentarea_tasks.infrastructure.models import Task as TaskORM

logger = logging.getLogger(__name__)


class TaskRepositoryInterface(BaseRepository[TaskDomain]):
    """Interface for task repository operations."""
    
    @abstractmethod
    async def get_by_status(self, status: TaskState) -> list[TaskDomain]:
        """Get tasks by status."""
        pass

    @abstractmethod
    async def get_by_user_id(self, user_id: str, limit: int = 100, offset: int = 0) -> list[TaskDomain]:
        """Get tasks created by a specific user."""
        pass

    @abstractmethod
    async def get_by_agent_id(self, agent_id: UUID, limit: int = 100, offset: int = 0) -> list[TaskDomain]:
        """Get tasks assigned to a specific agent."""
        pass

    @abstractmethod
    async def get_pending_tasks(self, limit: int = 20) -> list[TaskDomain]:
        """Get all pending tasks."""
        pass


def _orm_to_domain(task_orm: TaskORM) -> TaskDomain:
    """Convert SQLAlchemy Task to domain Task."""
    # Create a dict from the ORM object, handling the metadata field name
    task_dict = {
        key: value for key, value in task_orm.__dict__.items() 
        if not key.startswith('_')
    }
    # Map task_metadata back to metadata for the domain model
    if 'task_metadata' in task_dict:
        task_dict['metadata'] = task_dict.pop('task_metadata')
    
    return TaskDomain.model_validate(task_dict)


def _domain_to_orm(task: TaskDomain) -> TaskORM:
    """Convert domain Task to SQLAlchemy Task."""
    task_dict = task.model_dump()
    # Handle the metadata field name conflict
    task_dict["task_metadata"] = task_dict.pop("metadata", {})
    return TaskORM(**task_dict)


class SQLAlchemyTaskRepository(TaskRepositoryInterface):
    """SQLAlchemy implementation of task repository."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, id: UUID) -> TaskDomain | None:
        result = await self.session.execute(select(TaskORM).where(TaskORM.id == str(id)))
        task_orm = result.scalar_one_or_none()
        return _orm_to_domain(task_orm) if task_orm else None

    async def list(self) -> list[TaskDomain]:
        result = await self.session.execute(select(TaskORM))
        task_orms = result.scalars().all()
        return [_orm_to_domain(task_orm) for task_orm in task_orms]

    async def create(self, entity: TaskDomain) -> TaskDomain:
        task_orm = _domain_to_orm(entity)
        self.session.add(task_orm)
        await self.session.flush()
        return _orm_to_domain(task_orm)

    async def update(self, entity: TaskDomain) -> TaskDomain:
        task_orm = _domain_to_orm(entity)
        await self.session.merge(task_orm)
        await self.session.flush()
        return _orm_to_domain(task_orm)

    async def delete(self, id: UUID) -> bool:
        result = await self.session.execute(select(TaskORM).where(TaskORM.id == str(id)))
        task_orm = result.scalar_one_or_none()
        if task_orm:
            await self.session.delete(task_orm)
            await self.session.flush()
            return True
        return False

    async def get_by_status(self, status: TaskState) -> list[TaskDomain]:
        result = await self.session.execute(
            select(TaskORM).where(TaskORM.status.op('->>')('state') == status.value)
        )
        task_orms = result.scalars().all()
        return [_orm_to_domain(task_orm) for task_orm in task_orms]

    # Additional task-specific methods
    async def get_by_user_id(self, user_id: str, limit: int = 100, offset: int = 0) -> list[TaskDomain]:
        """Get tasks created by a specific user."""
        stmt = (
            select(TaskORM)
            .where(TaskORM.created_by == user_id)
            .order_by(TaskORM.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        task_orms = list(result.scalars().all())
        return [_orm_to_domain(task_orm) for task_orm in task_orms]

    async def get_by_agent_id(self, agent_id: UUID, limit: int = 100, offset: int = 0) -> list[TaskDomain]:
        """Get tasks assigned to a specific agent."""
        stmt = (
            select(TaskORM)
            .where(TaskORM.assigned_agent_id == str(agent_id))
            .order_by(TaskORM.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        task_orms = list(result.scalars().all())
        return [_orm_to_domain(task_orm) for task_orm in task_orms]

    async def get_pending_tasks(self, limit: int = 20) -> list[TaskDomain]:
        """Get all pending tasks."""
        stmt = (
            select(TaskORM)
            .where(TaskORM.status.op('->>')('state') == TaskState.SUBMITTED.value)
            .order_by(TaskORM.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        task_orms = list(result.scalars().all())
        return [_orm_to_domain(task_orm) for task_orm in task_orms]
