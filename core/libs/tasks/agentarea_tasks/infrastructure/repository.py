"""Task repository implementation."""

from datetime import datetime
from typing import Any, List
from uuid import UUID, uuid4

from agentarea_common.base.repository import BaseRepository
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import Task, TaskCreate, TaskUpdate
from .orm import TaskORM


class TaskRepository(BaseRepository[Task]):
    """Repository for task persistence."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get(self, id: UUID) -> Task | None:
        """Get a task by ID."""
        stmt = select(TaskORM).where(TaskORM.id == id)
        result = await self.session.execute(stmt)
        task_orm = result.scalar_one_or_none()
        
        if not task_orm:
            return None
        
        return self._orm_to_domain(task_orm)
    
    async def list(self) -> List[Task]:
        """List all tasks."""
        stmt = select(TaskORM).order_by(TaskORM.created_at.desc())
        result = await self.session.execute(stmt)
        task_orms = result.scalars().all()
        
        return [self._orm_to_domain(task_orm) for task_orm in task_orms]
    
    async def create(self, entity: Task) -> Task:
        """Create a new task from domain model."""
        task_orm = self._domain_to_orm(entity)
        
        self.session.add(task_orm)
        await self.session.flush()
        await self.session.refresh(task_orm)
        
        return self._orm_to_domain(task_orm)
    
    async def update(self, entity: Task) -> Task:
        """Update an existing task."""
        task_orm = self._domain_to_orm(entity)
        
        await self.session.merge(task_orm)
        await self.session.flush()
        
        return entity
    
    async def delete(self, id: UUID) -> bool:
        """Delete a task by ID."""
        stmt = select(TaskORM).where(TaskORM.id == id)
        result = await self.session.execute(stmt)
        task_orm = result.scalar_one_or_none()
        
        if not task_orm:
            return False
        
        await self.session.delete(task_orm)
        await self.session.flush()
        return True
    
    # Additional methods for task-specific operations
    async def create_from_data(self, task_data: TaskCreate) -> Task:
        """Create a new task from TaskCreate data."""
        task_orm = TaskORM(
            id=uuid4(),
            agent_id=task_data.agent_id,
            description=task_data.description,
            parameters=task_data.parameters,
            status="pending",
            created_at=datetime.utcnow(),
            user_id=task_data.user_id,
            task_metadata=task_data.metadata,
        )
        
        self.session.add(task_orm)
        await self.session.flush()
        await self.session.refresh(task_orm)
        
        return self._orm_to_domain(task_orm)
    
    async def update_by_id(self, task_id: UUID, task_update: TaskUpdate) -> Task | None:
        """Update a task by ID with TaskUpdate data."""
        # Build update dict excluding None values
        update_data = {}
        for field, value in task_update.dict(exclude_unset=True).items():
            if value is not None:
                if field == "metadata":
                    update_data["task_metadata"] = value
                else:
                    update_data[field] = value
        
        if not update_data:
            return await self.get(task_id)
        
        stmt = update(TaskORM).where(TaskORM.id == task_id).values(**update_data)
        await self.session.execute(stmt)
        await self.session.flush()
        
        return await self.get(task_id)
    
    async def list_by_agent(self, agent_id: UUID, limit: int = 100) -> List[Task]:
        """List tasks for an agent."""
        stmt = (
            select(TaskORM)
            .where(TaskORM.agent_id == agent_id)
            .order_by(TaskORM.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        task_orms = result.scalars().all()
        
        return [self._orm_to_domain(task_orm) for task_orm in task_orms]
    
    def _orm_to_domain(self, task_orm: TaskORM) -> Task:
        """Convert ORM model to domain model."""
        return Task(
            id=task_orm.id,
            agent_id=task_orm.agent_id,
            description=task_orm.description,
            parameters=task_orm.parameters or {},
            status=task_orm.status,
            result=task_orm.result,
            error=task_orm.error,
            created_at=task_orm.created_at,
            started_at=task_orm.started_at,
            completed_at=task_orm.completed_at,
            execution_id=task_orm.execution_id,
            user_id=task_orm.user_id,
            metadata=task_orm.task_metadata or {},
        )
    
    def _domain_to_orm(self, task: Task) -> TaskORM:
        """Convert domain model to ORM model."""
        return TaskORM(
            id=task.id,
            agent_id=task.agent_id,
            description=task.description,
            parameters=task.parameters,
            status=task.status,
            result=task.result,
            error=task.error,
            created_at=task.created_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            execution_id=task.execution_id,
            user_id=task.user_id,
            task_metadata=task.metadata,
        )