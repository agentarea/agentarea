"""Task repository for AgentArea platform.

Simple repository for task persistence operations.
"""

from __future__ import annotations

import logging
from uuid import UUID

from agentarea_common.base.repository import BaseRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_tasks.domain.models import SimpleTask
from agentarea_tasks.infrastructure.models import Task as TaskORM

logger = logging.getLogger(__name__)


class TaskRepository(BaseRepository[SimpleTask]):
    """Simple task repository for agent execution tasks."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, id: UUID) -> SimpleTask | None:
        result = await self.session.execute(select(TaskORM).where(TaskORM.id == id))
        task_orm = result.scalar_one_or_none()
        return self._orm_to_domain(task_orm) if task_orm else None

    async def list(self) -> list[SimpleTask]:
        result = await self.session.execute(select(TaskORM))
        task_orms = result.scalars().all()
        return [self._orm_to_domain(task_orm) for task_orm in task_orms]

    async def create(self, entity: SimpleTask) -> SimpleTask:
        task_orm = self._domain_to_orm(entity)
        self.session.add(task_orm)
        await self.session.flush()
        await self.session.refresh(task_orm)
        return self._orm_to_domain(task_orm)

    async def update(self, entity: SimpleTask) -> SimpleTask:
        # Find existing task
        result = await self.session.execute(select(TaskORM).where(TaskORM.id == entity.id))
        existing_orm = result.scalar_one_or_none()
        
        if not existing_orm:
            raise ValueError(f"Task with id {entity.id} not found")
            
        # Update fields
        existing_orm.title = entity.title
        existing_orm.description = entity.description
        existing_orm.query = entity.query
        existing_orm.status = entity.status
        existing_orm.user_id = entity.user_id
        existing_orm.agent_id = entity.agent_id
        existing_orm.task_parameters = entity.task_parameters or {}
        if entity.result is not None:
            existing_orm.result = entity.result
        if entity.error_message is not None:
            existing_orm.error_message = entity.error_message
        
        await self.session.flush()
        await self.session.refresh(existing_orm)
        return self._orm_to_domain(existing_orm)

    async def delete(self, id: UUID) -> bool:
        result = await self.session.execute(select(TaskORM).where(TaskORM.id == id))
        task_orm = result.scalar_one_or_none()
        if task_orm:
            await self.session.delete(task_orm)
            await self.session.flush()
            return True
        return False

    async def get_by_user_id(self, user_id: str, limit: int = 100, offset: int = 0) -> list[SimpleTask]:
        """Get tasks created by a specific user."""
        stmt = (
            select(TaskORM)
            .where(TaskORM.user_id == user_id)
            .order_by(TaskORM.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        task_orms = list(result.scalars().all())
        return [self._orm_to_domain(task_orm) for task_orm in task_orms]

    async def get_by_agent_id(self, agent_id: UUID, limit: int = 100, offset: int = 0) -> list[SimpleTask]:
        """Get tasks assigned to a specific agent."""
        stmt = (
            select(TaskORM)
            .where(TaskORM.agent_id == agent_id)
            .order_by(TaskORM.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        task_orms = list(result.scalars().all())
        return [self._orm_to_domain(task_orm) for task_orm in task_orms]

    async def get_by_status(self, status: str) -> list[SimpleTask]:
        """Get tasks by status."""
        result = await self.session.execute(
            select(TaskORM).where(TaskORM.status == status)
        )
        task_orms = result.scalars().all()
        return [self._orm_to_domain(task_orm) for task_orm in task_orms]

    def _orm_to_domain(self, task_orm: TaskORM) -> SimpleTask:
        """Convert SQLAlchemy Task to domain SimpleTask."""
        return SimpleTask(
            id=task_orm.id,
            title=task_orm.title,
            description=task_orm.description,
            query=task_orm.query,
            status=task_orm.status,
            user_id=task_orm.user_id,
            agent_id=task_orm.agent_id,
            task_parameters=task_orm.task_parameters or {},
            result=task_orm.result,
            error_message=task_orm.error_message,
            created_at=task_orm.created_at,
            updated_at=task_orm.updated_at,
        )

    def _domain_to_orm(self, task: SimpleTask) -> TaskORM:
        """Convert domain SimpleTask to SQLAlchemy Task."""
        return TaskORM(
            id=task.id,
            title=task.title,
            description=task.description,
            query=task.query,
            status=task.status,
            user_id=task.user_id,
            agent_id=task.agent_id,
            task_parameters=task.task_parameters,
            result=task.result,
            error_message=task.error_message,
        )
