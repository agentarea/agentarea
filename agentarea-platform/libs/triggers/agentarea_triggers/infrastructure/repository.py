"""Trigger repository implementation."""

from datetime import datetime
from enum import Enum
from typing import Any, NamedTuple, cast
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import ColumnElement, and_, desc, func, literal_column, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import ExecutionStatus, TriggerType
from ..domain.models import (
    RECONSTITUTING,
    CronTrigger,
    StreamTrigger,
    Trigger,
    TriggerBatchWindow,
    TriggerCreate,
    TriggerExecution,
    TriggerSession,
    TriggerUpdate,
)
from ..logging_utils import FiringNotRecordedError
from .orm import TriggerExecutionORM, TriggerORM

# A trigger's firing; a forward's reaction to a stream event has no trigger.
_A_FIRING = TriggerExecutionORM.trigger_id.is_not(None)


class FailureCount(NamedTuple):
    failures: int
    threshold: int
    active: bool


def _value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _session(session: TriggerSession | None) -> dict[str, Any] | None:
    return session.model_dump(by_alias=True, exclude_none=True) if session else None


def _batch(batch: TriggerBatchWindow | None) -> dict[str, Any] | None:
    return batch.model_dump(exclude_none=True) if batch else None


class TriggerRepository(WorkspaceScopedRepository[TriggerORM]):
    """Repository for trigger persistence."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, TriggerORM, user_context)

    async def names(self, ids: list[UUID]) -> dict[UUID, str]:
        if not ids:
            return {}
        result = await self.session.execute(
            select(TriggerORM.id, TriggerORM.name).where(
                TriggerORM.id.in_(ids), self._get_workspace_filter()
            )
        )
        return dict(result.tuples().all())

    async def get_trigger(self, id: UUID) -> Trigger | None:
        """Get a trigger by ID and convert to domain model."""
        trigger_orm = await self.get_by_id(id)
        if not trigger_orm:
            return None
        return self._orm_to_domain(trigger_orm)

    async def list_triggers(
        self, limit: int = 100, offset: int = 0, **filters: Any
    ) -> list[Trigger]:
        """List the workspace's triggers matching ``filters``, as domain models."""
        trigger_orms = await self.list_all(limit=limit, offset=offset, **filters)
        return [self._orm_to_domain(trigger_orm) for trigger_orm in trigger_orms]

    async def create_trigger(self, entity: Trigger) -> Trigger:
        """Create a new trigger from domain model."""
        # Extract fields from domain model
        trigger_data = {
            "id": entity.id,
            "name": entity.name,
            "description": entity.description,
            "agent_id": entity.agent_id,
            "trigger_type": _value(entity.trigger_type),
            "is_active": entity.is_active,
            "task_parameters": entity.task_parameters,
            "conditions": entity.conditions,
            "failure_threshold": entity.failure_threshold,
            "consecutive_failures": entity.consecutive_failures,
            "last_execution_at": entity.last_execution_at,
        }

        # Add type-specific fields
        if isinstance(entity, CronTrigger):
            trigger_data.update(
                {"cron_expression": entity.cron_expression, "timezone": entity.timezone}
            )
        elif isinstance(entity, StreamTrigger):
            trigger_data["session"] = _session(entity.session)

        # Remove None values and system fields that will be auto-populated
        trigger_data = {k: v for k, v in trigger_data.items() if v is not None}
        trigger_data.pop("created_at", None)
        trigger_data.pop("updated_at", None)

        trigger_orm = await self.create(**trigger_data)
        return self._orm_to_domain(trigger_orm)

    async def update_trigger(self, entity: Trigger) -> Trigger:
        """Update an existing trigger from domain model."""
        # Extract fields from domain model
        trigger_data = {
            "name": entity.name,
            "description": entity.description,
            "agent_id": entity.agent_id,
            "trigger_type": _value(entity.trigger_type),
            "is_active": entity.is_active,
            "task_parameters": entity.task_parameters,
            "conditions": entity.conditions,
            "failure_threshold": entity.failure_threshold,
            "consecutive_failures": entity.consecutive_failures,
            "last_execution_at": entity.last_execution_at,
        }

        # Add type-specific fields
        if isinstance(entity, CronTrigger):
            trigger_data.update(
                {"cron_expression": entity.cron_expression, "timezone": entity.timezone}
            )
        elif isinstance(entity, StreamTrigger):
            trigger_data["session"] = _session(entity.session)

        # Remove None values
        trigger_data = {k: v for k, v in trigger_data.items() if v is not None}

        trigger_orm = await self.update(entity.id, **trigger_data)
        if not trigger_orm:
            return entity  # Return original if update failed
        return self._orm_to_domain(trigger_orm)

    async def delete_trigger(self, id: UUID) -> bool:
        """Delete a trigger by ID."""
        return await self.delete(id)

    # Additional methods for trigger-specific operations
    async def create_from_model(self, trigger_data: TriggerCreate) -> Trigger:
        """Create a new trigger from TriggerCreate data."""
        trigger_orm = TriggerORM(
            # BaseModel automatically provides: id, created_at, updated_at
            name=trigger_data.name,
            description=trigger_data.description,
            agent_id=trigger_data.agent_id,
            trigger_type=_value(trigger_data.trigger_type),
            task_parameters=trigger_data.task_parameters,
            conditions=trigger_data.conditions,
            created_by=trigger_data.created_by,
            workspace_id=getattr(trigger_data, "workspace_id", None),
            is_active=trigger_data.is_active,
            failure_threshold=trigger_data.failure_threshold,
            cron_expression=trigger_data.cron_expression,
            timezone=trigger_data.timezone,
            session=_session(trigger_data.session),
            batch=_batch(trigger_data.batch),
        )

        self.session.add(trigger_orm)
        await self.session.flush()
        await self.session.refresh(trigger_orm)

        # Bypasses WorkspaceScopedRepository.create, so grant ownership explicitly.
        await self._record_graph_ownership(trigger_orm)

        return self._orm_to_domain(trigger_orm)

    async def update_by_id(self, trigger_id: UUID, trigger_update: TriggerUpdate) -> Trigger | None:
        """Update a trigger by ID with TriggerUpdate data."""
        # Build update dict excluding None values
        update_data = {}
        # event_filter lives on the trigger's stream subscription, not on the row.
        for field, value in trigger_update.model_dump(
            exclude_unset=True, exclude={"event_filter", "session", "batch"}
        ).items():
            if value is not None:
                update_data[field] = value
        if "session" in trigger_update.model_fields_set:
            update_data["session"] = _session(trigger_update.session)
        if "batch" in trigger_update.model_fields_set:
            update_data["batch"] = _batch(trigger_update.batch)

        if not update_data:
            return await self.get_trigger(trigger_id)

        if update_data.get("is_active") is True:
            update_data["needs_new_owner_at"] = None
        update_data["updated_at"] = datetime.utcnow()

        stmt = (
            update(TriggerORM)
            .where(TriggerORM.id == trigger_id, self._get_workspace_filter())
            .values(**update_data)
        )
        await self.session.execute(stmt)
        await self.session.flush()

        return await self.get_trigger(trigger_id)

    async def count_all(self) -> int:
        """Count all triggers visible in the current workspace."""
        return await self.count()

    async def update_execution_tracking(
        self, trigger_id: UUID, last_execution_at: datetime
    ) -> bool:
        """Stamp when the trigger last fired; the failure count moves only by count/reset."""
        stmt = (
            update(TriggerORM)
            .where(TriggerORM.id == trigger_id)
            .values(last_execution_at=last_execution_at, updated_at=datetime.utcnow())
        )
        result = await self.session.execute(stmt)
        await self.session.flush()

        return cast(CursorResult[Any], result).rowcount > 0

    async def lock(self, trigger_id: UUID) -> bool:
        """Lock the trigger's row for this transaction; False when it is gone."""
        found = await self.session.execute(
            select(TriggerORM.id)
            .where(TriggerORM.id == trigger_id, self._get_workspace_filter())
            .with_for_update()
        )
        return found.scalar_one_or_none() is not None

    async def count_failure(self, trigger_id: UUID) -> FailureCount | None:
        """Add one consecutive failure in one statement; the count after it."""
        row = (
            await self.session.execute(
                update(TriggerORM)
                .where(TriggerORM.id == trigger_id, self._get_workspace_filter())
                .values(
                    consecutive_failures=TriggerORM.consecutive_failures + 1,
                    updated_at=datetime.utcnow(),
                )
                .returning(
                    TriggerORM.consecutive_failures,
                    TriggerORM.failure_threshold,
                    TriggerORM.is_active,
                )
            )
        ).one_or_none()
        await self.session.flush()
        if row is None:
            return None
        return FailureCount(failures=row[0], threshold=row[1], active=row[2])

    async def reset_failures(self, trigger_id: UUID) -> None:
        await self.session.execute(
            update(TriggerORM)
            .where(
                TriggerORM.id == trigger_id,
                TriggerORM.consecutive_failures > 0,
                self._get_workspace_filter(),
            )
            .values(consecutive_failures=0, updated_at=datetime.utcnow())
        )
        await self.session.flush()

    async def disable_trigger(self, trigger_id: UUID) -> bool:
        """Disable a trigger in the current workspace."""
        stmt = (
            update(TriggerORM)
            .where(TriggerORM.id == trigger_id, self._get_workspace_filter())
            .values(is_active=False, updated_at=datetime.utcnow())
        )
        result = await self.session.execute(stmt)
        await self.session.flush()

        return cast(CursorResult[Any], result).rowcount > 0

    async def enable_trigger(self, trigger_id: UUID) -> bool:
        """Enable a trigger in the current workspace.

        Clears a "needs a new owner" stop: the next event re-checks the
        configurer's access and stops the trigger again if it is still missing.
        Starts the failure count over, so one failure after it does not stop it again.
        """
        stmt = (
            update(TriggerORM)
            .where(TriggerORM.id == trigger_id, self._get_workspace_filter())
            .values(
                is_active=True,
                needs_new_owner_at=None,
                consecutive_failures=0,
                updated_at=datetime.utcnow(),
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()

        return cast(CursorResult[Any], result).rowcount > 0

    async def mark_needs_new_owner(self, trigger_id: UUID) -> bool:
        """Stop a trigger whose configurer can no longer run its agent, and say why."""
        stmt = (
            update(TriggerORM)
            .where(TriggerORM.id == trigger_id, self._get_workspace_filter())
            .values(
                is_active=False,
                needs_new_owner_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return cast(CursorResult[Any], result).rowcount > 0

    def _orm_to_domain(self, trigger_orm: TriggerORM) -> Trigger:
        """Convert ORM model to domain model."""
        if trigger_orm.trigger_type not in {t.value for t in TriggerType}:
            raise ValueError(
                f"trigger {trigger_orm.id} has unknown type {trigger_orm.trigger_type!r}"
            )
        base_data = {
            "id": trigger_orm.id,
            "name": trigger_orm.name,
            "description": trigger_orm.description,
            "agent_id": trigger_orm.agent_id,
            "trigger_type": TriggerType(trigger_orm.trigger_type),
            "is_active": trigger_orm.is_active,
            "task_parameters": trigger_orm.task_parameters or {},
            "conditions": trigger_orm.conditions or {},
            "created_at": trigger_orm.created_at,
            "updated_at": trigger_orm.updated_at,
            "created_by": trigger_orm.created_by,
            "workspace_id": trigger_orm.workspace_id,
            "failure_threshold": trigger_orm.failure_threshold,
            "consecutive_failures": trigger_orm.consecutive_failures,
            "last_execution_at": trigger_orm.last_execution_at,
            "needs_new_owner_at": trigger_orm.needs_new_owner_at,
        }

        if trigger_orm.trigger_type == TriggerType.CRON.value:
            return CronTrigger.model_validate(
                {
                    **base_data,
                    "cron_expression": trigger_orm.cron_expression or "",
                    "timezone": trigger_orm.timezone or "UTC",
                },
                context=RECONSTITUTING,
            )
        return StreamTrigger.model_validate(
            {**base_data, "session": trigger_orm.session, "batch": trigger_orm.batch},
            context=RECONSTITUTING,
        )

    def _domain_to_orm(self, trigger: Trigger) -> TriggerORM:
        """Convert domain model to ORM model."""
        orm_data = {
            "id": trigger.id,
            "name": trigger.name,
            "description": trigger.description,
            "agent_id": trigger.agent_id,
            "trigger_type": _value(trigger.trigger_type),
            "is_active": trigger.is_active,
            "task_parameters": trigger.task_parameters,
            "conditions": trigger.conditions,
            "created_at": trigger.created_at,
            "updated_at": trigger.updated_at,
            "created_by": trigger.created_by,
            "workspace_id": trigger.workspace_id,
            "failure_threshold": trigger.failure_threshold,
            "consecutive_failures": trigger.consecutive_failures,
            "last_execution_at": trigger.last_execution_at,
        }

        if isinstance(trigger, CronTrigger):
            orm_data.update(
                {"cron_expression": trigger.cron_expression, "timezone": trigger.timezone}
            )
        elif isinstance(trigger, StreamTrigger):
            orm_data["session"] = _session(trigger.session)
            orm_data["batch"] = _batch(trigger.batch)

        return TriggerORM(**orm_data)


class TriggerExecutionRepository(WorkspaceScopedRepository[TriggerExecutionORM]):
    """Repository for trigger execution persistence."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, TriggerExecutionORM, user_context)

    async def get_execution(self, id: UUID) -> TriggerExecution | None:
        """Get a trigger execution by ID and convert to domain model."""
        execution_orm = await self.get_by_id(id)
        if not execution_orm:
            return None
        return self._orm_to_domain(execution_orm)

    async def list_executions(self, limit: int = 100, offset: int = 0) -> list[TriggerExecution]:
        """List all trigger executions in workspace and convert to domain models."""
        execution_orms = await self.list_all(limit=limit, offset=offset)
        return [self._orm_to_domain(execution_orm) for execution_orm in execution_orms]

    async def create_execution(self, entity: TriggerExecution) -> TriggerExecution:
        """Create a new trigger execution from domain model."""
        # Extract fields from domain model
        execution_data = {
            "id": entity.id,
            "trigger_id": entity.trigger_id,
            "executed_at": entity.executed_at,
            "status": entity.status.value,
            "task_id": entity.task_id,
            "execution_time_ms": entity.execution_time_ms,
            "error_message": entity.error_message,
            "trigger_data": entity.trigger_data,
            "workflow_id": entity.workflow_id,
            "run_id": entity.run_id,
            "fired_by": entity.fired_by,
        }

        # Remove None values and system fields that will be auto-populated
        execution_data = {k: v for k, v in execution_data.items() if v is not None}
        execution_data.pop("created_at", None)
        execution_data.pop("updated_at", None)

        execution_orm = await self.create(**execution_data)
        return self._orm_to_domain(execution_orm)

    async def update_execution(self, entity: TriggerExecution) -> TriggerExecution:
        """Update an existing trigger execution from domain model."""
        # Extract fields from domain model
        execution_data = {
            "trigger_id": entity.trigger_id,
            "executed_at": entity.executed_at,
            "status": entity.status.value,
            "task_id": entity.task_id,
            "execution_time_ms": entity.execution_time_ms,
            "error_message": entity.error_message,
            "trigger_data": entity.trigger_data,
            "workflow_id": entity.workflow_id,
            "run_id": entity.run_id,
            "fired_by": entity.fired_by,
        }

        # Remove None values
        execution_data = {k: v for k, v in execution_data.items() if v is not None}

        execution_orm = await self.update(entity.id, **execution_data)
        if not execution_orm:
            return entity  # Return original if update failed
        return self._orm_to_domain(execution_orm)

    async def delete_execution(self, id: UUID) -> bool:
        """Delete a trigger execution by ID."""
        return await self.delete(id)

    async def names_task(self, trigger_id: UUID, task_id: UUID) -> bool:
        """Whether a firing of the trigger already records the task."""
        found = await self.session.execute(
            select(TriggerExecutionORM.id)
            .where(
                TriggerExecutionORM.trigger_id == trigger_id,
                TriggerExecutionORM.task_id == task_id,
                self._get_workspace_filter(),
            )
            .limit(1)
        )
        return found.scalar_one_or_none() is not None

    async def mark_run_failed(self, trigger_id: UUID, task_id: UUID, error: str | None) -> bool:
        """Mark the latest firing that started the task failed; False when it is not a success.

        Raises FiringNotRecordedError when no firing of the trigger names the task.
        """
        latest = (
            await self.session.execute(
                select(TriggerExecutionORM.id, TriggerExecutionORM.status)
                .where(
                    TriggerExecutionORM.trigger_id == trigger_id,
                    TriggerExecutionORM.task_id == task_id,
                    self._get_workspace_filter(),
                )
                .order_by(desc(TriggerExecutionORM.executed_at))
                .limit(1)
                .with_for_update()
            )
        ).one_or_none()
        if latest is None:
            raise FiringNotRecordedError(
                f"no firing of trigger {trigger_id} names task {task_id} yet",
                trigger_id=str(trigger_id),
                task_id=str(task_id),
            )
        if latest.status != ExecutionStatus.SUCCESS.value:
            return False
        await self.session.execute(
            update(TriggerExecutionORM)
            .where(TriggerExecutionORM.id == latest.id)
            .values(
                status=ExecutionStatus.FAILED.value,
                error_message=error,
                updated_at=datetime.utcnow(),
            )
        )
        await self.session.flush()
        return True

    async def list_by_trigger(
        self, trigger_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[TriggerExecution]:
        """List executions for a specific trigger."""
        stmt = (
            select(TriggerExecutionORM)
            .where(TriggerExecutionORM.trigger_id == trigger_id)
            .order_by(desc(TriggerExecutionORM.executed_at))
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        execution_orms = result.scalars().all()

        return [self._orm_to_domain(execution_orm) for execution_orm in execution_orms]

    async def list_by_status(
        self, status: ExecutionStatus, limit: int = 100
    ) -> list[TriggerExecution]:
        """List executions by status."""
        stmt = (
            select(TriggerExecutionORM)
            .where(TriggerExecutionORM.status == status.value, _A_FIRING)
            .order_by(desc(TriggerExecutionORM.executed_at))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        execution_orms = result.scalars().all()

        return [self._orm_to_domain(execution_orm) for execution_orm in execution_orms]

    async def get_recent_executions(
        self, trigger_id: UUID, hours: int = 24, limit: int = 100
    ) -> list[TriggerExecution]:
        """Get recent executions for a trigger within specified hours."""
        from datetime import timedelta

        cutoff_time = datetime.utcnow() - timedelta(hours=hours)

        stmt = (
            select(TriggerExecutionORM)
            .where(
                and_(
                    TriggerExecutionORM.trigger_id == trigger_id,
                    TriggerExecutionORM.executed_at >= cutoff_time,
                )
            )
            .order_by(desc(TriggerExecutionORM.executed_at))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        execution_orms = result.scalars().all()

        return [self._orm_to_domain(execution_orm) for execution_orm in execution_orms]

    async def count_executions_in_period(
        self, trigger_id: UUID, start_time: datetime, end_time: datetime
    ) -> int:
        """Count executions for a trigger in a specific time period."""
        stmt = select(func.count(TriggerExecutionORM.id)).where(
            and_(
                TriggerExecutionORM.trigger_id == trigger_id,
                TriggerExecutionORM.executed_at >= start_time,
                TriggerExecutionORM.executed_at <= end_time,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    # Enhanced pagination and filtering methods for monitoring

    async def list_executions_paginated(
        self,
        trigger_id: UUID | None = None,
        status: ExecutionStatus | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TriggerExecution]:
        """List executions with pagination and filtering."""
        stmt = select(TriggerExecutionORM)

        # Apply filters
        conditions: list[ColumnElement[bool]] = [_A_FIRING]
        if trigger_id:
            conditions.append(TriggerExecutionORM.trigger_id == trigger_id)
        if status:
            conditions.append(TriggerExecutionORM.status == status.value)
        if start_time:
            conditions.append(TriggerExecutionORM.executed_at >= start_time)
        if end_time:
            conditions.append(TriggerExecutionORM.executed_at <= end_time)

        if conditions:
            stmt = stmt.where(and_(*conditions))

        stmt = stmt.order_by(desc(TriggerExecutionORM.executed_at)).limit(limit).offset(offset)

        result = await self.session.execute(stmt)
        execution_orms = result.scalars().all()

        return [self._orm_to_domain(execution_orm) for execution_orm in execution_orms]

    async def count_executions_filtered(
        self,
        trigger_id: UUID | None = None,
        status: ExecutionStatus | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> int:
        """Count executions with filtering."""
        stmt = select(func.count(TriggerExecutionORM.id))

        # Apply filters
        conditions: list[ColumnElement[bool]] = [_A_FIRING]
        if trigger_id:
            conditions.append(TriggerExecutionORM.trigger_id == trigger_id)
        if status:
            conditions.append(TriggerExecutionORM.status == status.value)
        if start_time:
            conditions.append(TriggerExecutionORM.executed_at >= start_time)
        if end_time:
            conditions.append(TriggerExecutionORM.executed_at <= end_time)

        if conditions:
            stmt = stmt.where(and_(*conditions))

        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_since(self, since: datetime) -> int:
        """Count executions since the given timestamp."""
        return await self.count_executions_filtered(start_time=since)

    async def count_failures_since(self, since: datetime) -> int:
        """Count failed or timed-out executions since the given timestamp."""
        failed = await self.count_executions_filtered(
            status=ExecutionStatus.FAILED, start_time=since
        )
        timed_out = await self.count_executions_filtered(
            status=ExecutionStatus.TIMEOUT, start_time=since
        )
        return failed + timed_out

    async def get_execution_metrics(
        self, trigger_id: UUID, hours: int | None = 24
    ) -> dict[str, Any]:
        """Get execution metrics for a trigger. ``hours=None`` covers all history."""
        from datetime import timedelta

        from sqlalchemy import case, func

        window = [TriggerExecutionORM.trigger_id == trigger_id]
        if hours is not None:
            window.append(
                TriggerExecutionORM.executed_at >= datetime.utcnow() - timedelta(hours=hours)
            )

        # Get aggregated metrics
        stmt = select(
            func.count(TriggerExecutionORM.id).label("total_executions"),
            func.count(
                case((TriggerExecutionORM.status == ExecutionStatus.SUCCESS.value, 1))
            ).label("successful_executions"),
            func.count(case((TriggerExecutionORM.status == ExecutionStatus.FAILED.value, 1))).label(
                "failed_executions"
            ),
            func.count(
                case((TriggerExecutionORM.status == ExecutionStatus.TIMEOUT.value, 1))
            ).label("timeout_executions"),
            func.count(
                case((TriggerExecutionORM.status == ExecutionStatus.SKIPPED.value, 1))
            ).label("skipped_executions"),
            func.avg(TriggerExecutionORM.execution_time_ms).label("avg_execution_time_ms"),
            func.min(TriggerExecutionORM.execution_time_ms).label("min_execution_time_ms"),
            func.max(TriggerExecutionORM.execution_time_ms).label("max_execution_time_ms"),
        ).where(and_(*window))

        result = await self.session.execute(stmt)
        row = result.first()

        if not row or row.total_executions == 0:
            return {
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "timeout_executions": 0,
                "skipped_executions": 0,
                "success_rate": 0.0,
                "failure_rate": 0.0,
                "avg_execution_time_ms": 0.0,
                "min_execution_time_ms": 0,
                "max_execution_time_ms": 0,
                "period_hours": hours,
            }

        total = row.total_executions
        successful = row.successful_executions or 0
        failed = row.failed_executions or 0
        timeout = row.timeout_executions or 0
        # An event the conditions turned away was never an attempt, so the
        # rates are over the runs that tried to start a task.
        attempts = successful + failed + timeout

        return {
            "total_executions": total,
            "successful_executions": successful,
            "failed_executions": failed,
            "timeout_executions": timeout,
            "skipped_executions": row.skipped_executions or 0,
            "success_rate": (successful / attempts) * 100 if attempts else 0.0,
            "failure_rate": ((failed + timeout) / attempts) * 100 if attempts else 0.0,
            "avg_execution_time_ms": float(row.avg_execution_time_ms or 0),
            "min_execution_time_ms": row.min_execution_time_ms or 0,
            "max_execution_time_ms": row.max_execution_time_ms or 0,
            "period_hours": hours,
        }

    async def get_executions_with_task_correlation(
        self, trigger_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Get executions with task correlation information."""
        # This would require joining with task tables if available
        # For now, we'll return execution data with task_id correlation
        executions = await self.list_by_trigger(trigger_id, limit, offset)

        # Convert to dict format with correlation info
        result = []
        for execution in executions:
            execution_dict = {
                "id": execution.id,
                "trigger_id": execution.trigger_id,
                "executed_at": execution.executed_at,
                "status": execution.status.value,
                "task_id": execution.task_id,
                "execution_time_ms": execution.execution_time_ms,
                "error_message": execution.error_message,
                "trigger_data": execution.trigger_data,
                "workflow_id": execution.workflow_id,
                "run_id": execution.run_id,
                "has_task_correlation": execution.task_id is not None,
                "has_workflow_correlation": execution.workflow_id is not None,
            }
            result.append(execution_dict)

        return result

    async def get_execution_timeline(
        self, trigger_id: UUID, hours: int = 24, bucket_size_minutes: int = 60
    ) -> list[dict[str, Any]]:
        """Get execution timeline with bucketed counts."""
        from datetime import timedelta

        from sqlalchemy import case, func

        cutoff_time = datetime.utcnow() - timedelta(hours=hours)

        # Create time buckets. Keep the date_trunc precision as a SQL literal:
        # asyncpg binds repeated "hour" strings as separate parameters, and
        # Postgres then treats SELECT/GROUP BY expressions as different.
        time_bucket = func.date_trunc(literal_column("'hour'"), TriggerExecutionORM.executed_at)
        stmt = (
            select(
                time_bucket.label("time_bucket"),
                func.count(TriggerExecutionORM.id).label("total_count"),
                func.count(
                    case((TriggerExecutionORM.status == ExecutionStatus.SUCCESS.value, 1))
                ).label("success_count"),
                func.count(
                    case((TriggerExecutionORM.status == ExecutionStatus.FAILED.value, 1))
                ).label("failed_count"),
                func.count(
                    case((TriggerExecutionORM.status == ExecutionStatus.TIMEOUT.value, 1))
                ).label("timeout_count"),
            )
            .where(
                and_(
                    TriggerExecutionORM.trigger_id == trigger_id,
                    TriggerExecutionORM.executed_at >= cutoff_time,
                )
            )
            .group_by(time_bucket)
            .order_by(time_bucket)
        )

        result = await self.session.execute(stmt)
        rows = result.all()

        timeline = []
        for row in rows:
            timeline.append(
                {
                    "time_bucket": row.time_bucket,
                    "total_count": row.total_count,
                    "success_count": row.success_count or 0,
                    "failed_count": row.failed_count or 0,
                    "timeout_count": row.timeout_count or 0,
                    "success_rate": (row.success_count / row.total_count * 100)
                    if row.total_count > 0
                    else 0.0,
                }
            )

        return timeline

    def _orm_to_domain(self, execution_orm: TriggerExecutionORM) -> TriggerExecution:
        """Convert ORM model to domain model."""
        if execution_orm.trigger_id is None:
            raise ValueError(
                f"trigger execution {execution_orm.id} is a forward's reaction, not a firing"
            )
        return TriggerExecution(
            id=cast(UUID, execution_orm.id),
            trigger_id=execution_orm.trigger_id,
            executed_at=execution_orm.executed_at,
            status=ExecutionStatus(execution_orm.status),
            task_id=execution_orm.task_id,
            execution_time_ms=execution_orm.execution_time_ms,
            error_message=execution_orm.error_message,
            trigger_data=execution_orm.trigger_data or {},
            workflow_id=execution_orm.workflow_id,
            run_id=execution_orm.run_id,
            fired_by=execution_orm.fired_by,
        )

    def _domain_to_orm(self, execution: TriggerExecution) -> TriggerExecutionORM:
        """Convert domain model to ORM model."""
        return TriggerExecutionORM(
            id=execution.id,
            trigger_id=execution.trigger_id,
            executed_at=execution.executed_at,
            status=execution.status.value,
            task_id=execution.task_id,
            execution_time_ms=execution.execution_time_ms,
            error_message=execution.error_message,
            trigger_data=execution.trigger_data,
            workflow_id=execution.workflow_id,
            run_id=execution.run_id,
            fired_by=execution.fired_by,
        )
