"""Task repository implementation."""

from datetime import UTC, datetime
from typing import Any
from typing import cast as type_cast
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import Numeric, cast, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import Task, TaskCreate, TaskEvent, TaskUpdate
from .orm import TaskEventORM, TaskORM


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

    async def list_tasks(
        self, limit: int = 100, offset: int = 0, creator_scoped: bool = False
    ) -> list[Task]:
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
            "id": entity.id,
            "agent_id": entity.agent_id,
            "description": entity.description,
            "parameters": entity.parameters,
            "status": entity.status,
            "result": entity.result,
            "error": entity.error,
            "started_at": entity.started_at,
            "completed_at": entity.completed_at,
            "execution_id": entity.execution_id,
            "task_metadata": metadata,
        }

        # Remove None values and system fields that will be auto-populated
        task_data = {k: v for k, v in task_data.items() if v is not None}
        task_data.pop("created_at", None)
        task_data.pop("updated_at", None)

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
            "agent_id": entity.agent_id,
            "description": entity.description,
            "parameters": entity.parameters,
            "status": entity.status,
            "result": entity.result,
            "error": entity.error,
            "started_at": entity.started_at,
            "completed_at": entity.completed_at,
            "execution_id": entity.execution_id,
            "task_metadata": metadata,
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

    async def list_by_agent(self, agent_id: UUID, limit: int = 100) -> list[Task]:
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

    async def get_by_agent_id(
        self, agent_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[Task]:
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

    async def get_by_status(self, status: str) -> list[Task]:
        """Get tasks by status."""
        stmt = select(TaskORM).where(TaskORM.status == status).order_by(TaskORM.created_at.desc())
        result = await self.session.execute(stmt)
        task_orms = result.scalars().all()

        return [self._orm_to_domain(task_orm) for task_orm in task_orms]

    async def list_by_statuses(
        self,
        statuses: list[str],
        agent_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Task]:
        """List tasks matching any of the given statuses, ordered by updated_at desc."""
        stmt = (
            select(TaskORM)
            .where(self._get_workspace_filter())
            .where(TaskORM.status.in_(statuses))
            .order_by(TaskORM.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if agent_id is not None:
            stmt = stmt.where(TaskORM.agent_id == agent_id)

        result = await self.session.execute(stmt)
        task_orms = result.scalars().all()
        return [self._orm_to_domain(task_orm) for task_orm in task_orms]

    async def find_active_by_agent_and_chat(
        self, agent_id: UUID, chat_id: str, limit: int = 5
    ) -> list[Task]:
        """Find recent active tasks for an agent + chat_id combination.

        Used for follow-up routing: if an active workflow exists for the same
        channel conversation, we route the message there instead of creating a new task.
        """
        stmt = (
            select(TaskORM)
            .where(
                self._get_workspace_filter(),
                TaskORM.agent_id == agent_id,
                TaskORM.status.in_(["running", "completed"]),
                TaskORM.execution_id.isnot(None),
                TaskORM.parameters["channel_origin"]["chat_id"].as_string() == chat_id,
            )
            .order_by(TaskORM.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [self._orm_to_domain(t) for t in result.scalars().all()]

    async def count_by_statuses(self, statuses: list[str]) -> int:
        """Count tasks matching any of the given statuses in the current workspace."""
        stmt = (
            select(func.count(TaskORM.id))
            .where(self._get_workspace_filter())
            .where(TaskORM.status.in_(statuses))
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def sum_spend_since(self, since: datetime) -> float:
        """Sum task.result.total_cost for the current workspace since a given UTC time.

        Uses started_at (falling back to created_at when started_at is null)
        as the activity timestamp. Tasks with no total_cost contribute 0.
        ``TaskORM.result`` is a plain JSON column, so we extract via the
        ``->>`` operator (returns text) and cast to numeric.
        """
        cost_expr = cast(TaskORM.result.op("->>")("total_cost"), Numeric)
        activity_at = func.coalesce(TaskORM.started_at, TaskORM.created_at)
        stmt = (
            select(func.coalesce(func.sum(cost_expr), 0))
            .where(self._get_workspace_filter())
            .where(activity_at >= since)
        )
        result = await self.session.execute(stmt)
        return float(result.scalar() or 0.0)

    async def sum_spend_mtd(self) -> float:
        """Sum total_cost for the current workspace from the first of this UTC month."""
        now = datetime.now(UTC)
        first_of_month = datetime(now.year, now.month, 1, tzinfo=UTC).replace(tzinfo=None)
        return await self.sum_spend_since(first_of_month)

    async def sum_spend_today(self) -> float:
        """Sum total_cost for the current workspace from the start of today UTC."""
        now = datetime.now(UTC)
        today_start = datetime(now.year, now.month, now.day, tzinfo=UTC).replace(tzinfo=None)
        return await self.sum_spend_since(today_start)

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

        if type_cast(CursorResult[Any], result).rowcount == 0:
            return None

        await self.session.flush()
        return await self.get_task(task_id)

    def _orm_to_domain(self, task_orm: TaskORM) -> Task:
        """Convert ORM model to domain model."""
        task_metadata = task_orm.task_metadata or {}

        # Ensure metadata is always a dict
        if not isinstance(task_metadata, dict):
            task_metadata = {}

        return Task.model_validate(
            {
                "id": task_orm.id,
                "agent_id": task_orm.agent_id,
                "description": task_orm.description,
                "parameters": task_orm.parameters or {},
                "status": task_orm.status,
                "result": task_orm.result,
                "error": task_orm.error,
                "created_at": task_orm.created_at,
                "updated_at": task_orm.updated_at,  # Added to match BaseModel
                "started_at": task_orm.started_at,
                "completed_at": task_orm.completed_at,
                "execution_id": task_orm.execution_id,
                "user_id": task_orm.created_by,
                "workspace_id": task_orm.workspace_id,
                "metadata": task_metadata,
            }
        )

    def _domain_to_orm(self, task) -> TaskORM:
        """Convert domain model to ORM model.

        Handles both Task and SimpleTask domain models.
        """
        # Handle different domain model types
        if hasattr(task, "task_parameters"):
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


class TaskEventRepository(WorkspaceScopedRepository[TaskEventORM]):
    """Repository for task event persistence."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, TaskEventORM, user_context)

    async def create_event(self, event: TaskEvent) -> TaskEvent:
        """Create a new task event."""
        event_orm = TaskEventORM(
            id=event.id,
            task_id=event.task_id,
            event_type=event.event_type,
            timestamp=event.timestamp,
            data=event.data,
            metadata=event.metadata,
            workspace_id=event.workspace_id,
            created_by=event.created_by,
        )

        self.session.add(event_orm)
        await self.session.flush()
        await self.session.refresh(event_orm)

        return self._orm_to_domain(event_orm)

    async def get_events_for_task(
        self, task_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[TaskEvent]:
        """Get events for a specific task."""
        stmt = (
            select(TaskEventORM)
            .where(TaskEventORM.task_id == task_id)
            .where(TaskEventORM.workspace_id == self.user_context.workspace_id)
            .order_by(TaskEventORM.timestamp.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        event_orms = result.scalars().all()

        return [self._orm_to_domain(event_orm) for event_orm in event_orms]

    async def get_events_by_type(
        self, event_type: str, limit: int = 100, offset: int = 0
    ) -> list[TaskEvent]:
        """Get events by type."""
        stmt = (
            select(TaskEventORM)
            .where(TaskEventORM.event_type == event_type)
            .where(TaskEventORM.workspace_id == self.user_context.workspace_id)
            .order_by(TaskEventORM.timestamp.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        event_orms = result.scalars().all()

        return [self._orm_to_domain(event_orm) for event_orm in event_orms]

    def _orm_to_domain(self, event_orm: TaskEventORM) -> TaskEvent:
        """Convert ORM model to domain model."""
        return TaskEvent.model_validate(
            {
                "id": event_orm.id,
                "task_id": event_orm.task_id,
                "event_type": event_orm.event_type,
                "timestamp": event_orm.timestamp,
                "data": event_orm.data or {},
                "metadata": event_orm.event_metadata or {},
                "workspace_id": event_orm.workspace_id,
                "created_by": event_orm.created_by,
            }
        )
