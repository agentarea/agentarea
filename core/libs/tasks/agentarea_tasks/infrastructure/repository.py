"""Task repository implementation."""

import builtins
from datetime import datetime
from typing import List
from uuid import UUID

from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from agentarea_common.auth.context import UserContext
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import Task, TaskCreate, TaskUpdate
from .orm import TaskORM


class TaskRepository(WorkspaceScopedRepository[TaskORM]):
    """Repository for task persistence."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, TaskORM, user_context)

    async def get_task(self, id: UUID) -> Task | None:
        """Get a task by ID and convert to domain model."""
        task_orm = await self.get_by_id(id)
        if not task_orm:
            return None
        return self._orm_to_domain(task_orm)

    async def list_tasks(self, limit: int = 100, offset: int = 0, creator_scoped: bool = False) -> List[Task]:
        """List all tasks in workspace and convert to domain models."""
        task_orms = await self.list_all(creator_scoped=creator_scoped, limit=limit, offset=offset)
        return [self._orm_to_domain(task_orm) for task_orm in task_orms]

    async def create_task(self, entity: Task) -> Task:
        """Create a new task from domain model."""
        # Handle metadata field - ensure it's JSON serializable
        metadata = entity.metadata
        if metadata is not None and not isinstance(metadata, dict):
            # If it's not a dict (e.g., SQLAlchemy MetaData), convert to empty dict
            metadata = {}
        
        # Extract fields from domain model
        task_data = {
            'id': entity.id,
            'agent_id': entity.agent_id,
            'description': entity.description,
            'parameters': entity.parameters,
            'status': entity.status,
            'result': entity.result,
            'error': entity.error,
            'started_at': entity.started_at,
            'completed_at': entity.completed_at,
            'execution_id': entity.execution_id,
            'task_metadata': metadata,
        }
        
        # Remove None values and system fields that will be auto-populated
        task_data = {k: v for k, v in task_data.items() if v is not None}
        task_data.pop('created_at', None)
        task_data.pop('updated_at', None)
        
        task_orm = await self.create(**task_data)
        return self._orm_to_domain(task_orm)

    async def update_task(self, entity: Task) -> Task:
        """Update an existing task from domain model."""
        # Handle metadata field - ensure it's JSON serializable
        metadata = entity.metadata
        if metadata is not None and not isinstance(metadata, dict):
            # If it's not a dict (e.g., SQLAlchemy MetaData), convert to empty dict
            metadata = {}
        
        # Extract fields from domain model
        task_data = {
            'agent_id': entity.agent_id,
            'description': entity.description,
            'parameters': entity.parameters,
            'status': entity.status,
            'result': entity.result,
            'error': entity.error,
            'started_at': entity.started_at,
            'completed_at': entity.completed_at,
            'execution_id': entity.execution_id,
            'task_metadata': metadata,
        }
        
        # Remove None values
        task_data = {k: v for k, v in task_data.items() if v is not None}
        
        task_orm = await self.update(entity.id, **task_data)
        if not task_orm:
            return entity  # Return original if update failed
        return self._orm_to_domain(task_orm)

    async def delete_task(self, id: UUID) -> bool:
        """Delete a task by ID."""
        return await self.delete(id)

    # Additional methods for task-specific operations
    async def create_from_data(self, task_data: TaskCreate) -> Task:
        """Create a new task from TaskCreate data."""
        # Handle metadata field - ensure it's JSON serializable
        metadata = task_data.metadata
        if metadata is not None and not isinstance(metadata, dict):
            # If it's not a dict (e.g., SQLAlchemy MetaData), convert to empty dict
            metadata = {}
        
        task_orm = TaskORM(
            # BaseModel automatically provides: id, created_at, updated_at
            agent_id=task_data.agent_id,
            description=task_data.description,
            parameters=task_data.parameters,
            status="pending",
            created_by=task_data.user_id or self.user_context.user_id,
            workspace_id=task_data.workspace_id or self.user_context.workspace_id,
            task_metadata=metadata,
        )


        self.session.add(task_orm)
        await self.session.flush()
        await self.session.refresh(task_orm)
        
        result = self._orm_to_domain(task_orm)
        return result

    async def update_by_id(self, task_id: UUID, task_update: TaskUpdate) -> Task | None:
        """Update a task by ID with TaskUpdate data."""
        # Build update dict excluding None values
        update_data = {}
        for field, value in task_update.dict(exclude_unset=True).items():
            if value is not None:
                if field == "metadata":
                    # Handle metadata field - ensure it's JSON serializable
                    if value is not None and not isinstance(value, dict):
                        # If it's not a dict (e.g., SQLAlchemy MetaData), convert to empty dict
                        value = {}
                    update_data["task_metadata"] = value
                else:
                    update_data[field] = value

        if not update_data:
            return await self.get_task(task_id)

        stmt = update(TaskORM).where(TaskORM.id == task_id).values(**update_data)
        await self.session.execute(stmt)
        await self.session.flush()

        return await self.get_task(task_id)

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

    async def get_by_agent_id(self, agent_id: UUID, limit: int = 100, offset: int = 0) -> List[Task]:
        """Get tasks by agent ID with pagination."""
        stmt = (
            select(TaskORM)
            .where(TaskORM.agent_id == agent_id)
            .order_by(TaskORM.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        task_orms = result.scalars().all()

        return [self._orm_to_domain(task_orm) for task_orm in task_orms]

    async def get_by_user_id(self, user_id: str, limit: int = 100, offset: int = 0) -> List[Task]:
        """Get tasks by user ID with pagination.
        
        Note: This method is deprecated. Use list_tasks(creator_scoped=True) instead.
        """
        # For backward compatibility - filter by creator in current workspace
        task_orms = await self.list_all(creator_scoped=True, limit=limit, offset=offset)
        return [self._orm_to_domain(task_orm) for task_orm in task_orms]

    async def get_by_workspace_id(self, workspace_id: str, limit: int = 100, offset: int = 0) -> List[Task]:
        """Get tasks by workspace ID with pagination.
        
        Note: This method is deprecated. Use list_tasks() instead which automatically
        filters by the current workspace from user context.
        """
        # For backward compatibility, but this should be replaced with list_tasks()
        if workspace_id != self.user_context.workspace_id:
            return []  # Don't allow cross-workspace access
        
        return await self.list_tasks(limit=limit, offset=offset)

    async def get_by_user_and_workspace(self, user_id: str, workspace_id: str, limit: int = 100, offset: int = 0) -> List[Task]:
        """Get tasks by both user ID and workspace ID with pagination.
        
        Note: This method is deprecated. Use list_tasks(creator_scoped=True) instead.
        """
        # For backward compatibility - filter by creator in current workspace
        if workspace_id != self.user_context.workspace_id:
            return []  # Don't allow cross-workspace access
        
        return await self.list_tasks(creator_scoped=True, limit=limit, offset=offset)

    async def get_by_status(self, status: str) -> List[Task]:
        """Get tasks by status."""
        stmt = (
            select(TaskORM)
            .where(TaskORM.status == status)
            .order_by(TaskORM.created_at.desc())
        )
        result = await self.session.execute(stmt)
        task_orms = result.scalars().all()

        return [self._orm_to_domain(task_orm) for task_orm in task_orms]

    async def update_status(self, task_id: UUID, status: str, **additional_fields) -> Task | None:
        """Update task status atomically with optional additional fields."""
        update_data = {"status": status, "updated_at": datetime.utcnow()}

        # Add any additional fields provided
        for field, value in additional_fields.items():
            if field == "metadata":
                # Handle metadata field - ensure it's JSON serializable
                if value is not None and not isinstance(value, dict):
                    # If it's not a dict (e.g., SQLAlchemy MetaData), convert to empty dict
                    value = {}
                update_data["task_metadata"] = value
            else:
                update_data[field] = value

        stmt = update(TaskORM).where(TaskORM.id == task_id).values(**update_data)
        result = await self.session.execute(stmt)

        if result.rowcount == 0:
            return None

        await self.session.flush()
        return await self.get_task(task_id)

    def _orm_to_domain(self, task_orm: TaskORM) -> Task:
        """Convert ORM model to domain model."""
        task_metadata = task_orm.task_metadata or {}
        
        # Ensure metadata is always a dict
        if not isinstance(task_metadata, dict):
            task_metadata = {}
        
        return Task.model_validate({
            'id': task_orm.id,
            'agent_id': task_orm.agent_id,
            'description': task_orm.description,
            'parameters': task_orm.parameters or {},
            'status': task_orm.status,
            'result': task_orm.result,
            'error': task_orm.error,
            'created_at': task_orm.created_at,
            'updated_at': task_orm.updated_at,  # Added to match BaseModel
            'started_at': task_orm.started_at,
            'completed_at': task_orm.completed_at,
            'execution_id': task_orm.execution_id,
            'user_id': task_orm.created_by,
            'workspace_id': task_orm.workspace_id,
            'metadata': task_metadata,
        })

    def _domain_to_orm(self, task) -> TaskORM:
        """Convert domain model to ORM model.

        Handles both Task and SimpleTask domain models.
        """
        # Handle different domain model types
        if hasattr(task, 'task_parameters'):
            # SimpleTask model
            parameters = task.task_parameters
            error = task.error_message
        else:
            # Task model
            parameters = task.parameters
            error = task.error

        return TaskORM(
            id=task.id,
            agent_id=task.agent_id,
            description=task.description,
            parameters=parameters,
            status=task.status,
            result=task.result,
            error=error,
            created_at=task.created_at,
            updated_at=task.updated_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            execution_id=task.execution_id,
            user_id=task.user_id,
            workspace_id=task.workspace_id,
            task_metadata=task.metadata,
        )
