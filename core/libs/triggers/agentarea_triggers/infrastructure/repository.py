"""Trigger repository implementation."""

from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import and_, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import ExecutionStatus, TriggerType
from ..domain.models import (
    CronTrigger,
    Trigger,
    TriggerCreate,
    TriggerExecution,
    TriggerUpdate,
    WebhookTrigger,
)
from .orm import TriggerExecutionORM, TriggerORM


class TriggerRepository(WorkspaceScopedRepository[TriggerORM]):
    """Repository for trigger persistence."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, TriggerORM, user_context)

    async def get_trigger(self, id: UUID) -> Trigger | None:
        """Get a trigger by ID and convert to domain model."""
        trigger_orm = await self.get_by_id(id)
        if not trigger_orm:
            return None
        return self._orm_to_domain(trigger_orm)

    async def list_triggers(
        self, limit: int = 100, offset: int = 0, creator_scoped: bool = False
    ) -> list[Trigger]:
        """List all triggers in workspace and convert to domain models."""
        trigger_orms = await self.list_all(
            creator_scoped=creator_scoped, limit=limit, offset=offset
        )
        return [self._orm_to_domain(trigger_orm) for trigger_orm in trigger_orms]

    async def create_trigger(self, entity: Trigger) -> Trigger:
        """Create a new trigger from domain model."""
        # Extract fields from domain model
        trigger_data = {
            "id": entity.id,
            "name": entity.name,
            "description": entity.description,
            "agent_id": entity.agent_id,
            "trigger_type": entity.trigger_type.value,
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
                {
                    "cron_expression": entity.cron_expression,
                    "timezone": entity.timezone,
                    "next_run_time": entity.next_run_time,
                }
            )
        elif isinstance(entity, WebhookTrigger):
            trigger_data.update(
                {
                    "webhook_id": entity.webhook_id,
                    "allowed_methods": entity.allowed_methods,
                    "webhook_type": entity.webhook_type.value,
                    "validation_rules": entity.validation_rules,
                    "webhook_config": entity.webhook_config,
                }
            )

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
            "trigger_type": entity.trigger_type.value,
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
                {
                    "cron_expression": entity.cron_expression,
                    "timezone": entity.timezone,
                    "next_run_time": entity.next_run_time,
                }
            )
        elif isinstance(entity, WebhookTrigger):
            trigger_data.update(
                {
                    "webhook_id": entity.webhook_id,
                    "allowed_methods": entity.allowed_methods,
                    "webhook_type": entity.webhook_type.value,
                    "validation_rules": entity.validation_rules,
                    "webhook_config": entity.webhook_config,
                }
            )

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
            trigger_type=trigger_data.trigger_type.value,
            task_parameters=trigger_data.task_parameters,
            conditions=trigger_data.conditions,
            created_by=trigger_data.created_by,
            workspace_id=getattr(trigger_data, "workspace_id", None),
            failure_threshold=trigger_data.failure_threshold,
            # Cron-specific fields
            cron_expression=trigger_data.cron_expression,
            timezone=trigger_data.timezone,
            # Webhook-specific fields
            webhook_id=trigger_data.webhook_id,
            allowed_methods=trigger_data.allowed_methods,
            webhook_type=trigger_data.webhook_type.value if trigger_data.webhook_type else None,
            validation_rules=trigger_data.validation_rules,
            webhook_config=trigger_data.webhook_config,
        )

        self.session.add(trigger_orm)
        await self.session.flush()
        await self.session.refresh(trigger_orm)

        return self._orm_to_domain(trigger_orm)

    async def update_by_id(self, trigger_id: UUID, trigger_update: TriggerUpdate) -> Trigger | None:
        """Update a trigger by ID with TriggerUpdate data."""
        # Build update dict excluding None values
        update_data = {}
        for field, value in trigger_update.dict(exclude_unset=True).items():
            if value is not None:
                if field == "webhook_type" and hasattr(value, "value"):
                    update_data[field] = value.value
                else:
                    update_data[field] = value

        if not update_data:
            return await self.get(trigger_id)

        update_data["updated_at"] = datetime.utcnow()

        stmt = update(TriggerORM).where(TriggerORM.id == trigger_id).values(**update_data)
        await self.session.execute(stmt)
        await self.session.flush()

        return await self.get(trigger_id)

    async def list_by_agent(self, agent_id: UUID, limit: int = 100) -> list[Trigger]:
        """List triggers for an agent."""
        stmt = (
            select(TriggerORM)
            .where(TriggerORM.agent_id == agent_id)
            .order_by(TriggerORM.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        trigger_orms = result.scalars().all()

        return [self._orm_to_domain(trigger_orm) for trigger_orm in trigger_orms]

    async def get_by_workspace_id(
        self, workspace_id: str, limit: int = 100, offset: int = 0
    ) -> list[Trigger]:
        """Get triggers by workspace ID with pagination.

        Note: This method is deprecated. Use list_triggers() instead which automatically
        filters by the current workspace from user context.
        """
        # For backward compatibility, but this should be replaced with list_triggers()
        if workspace_id != self.user_context.workspace_id:
            return []  # Don't allow cross-workspace access

        return await self.list_triggers(limit=limit, offset=offset)

    async def list_by_type(self, trigger_type: TriggerType, limit: int = 100) -> list[Trigger]:
        """List triggers by type."""
        stmt = (
            select(TriggerORM)
            .where(TriggerORM.trigger_type == trigger_type.value)
            .order_by(TriggerORM.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        trigger_orms = result.scalars().all()

        return [self._orm_to_domain(trigger_orm) for trigger_orm in trigger_orms]

    async def list_active_triggers(self, limit: int = 100) -> list[Trigger]:
        """List active triggers."""
        stmt = (
            select(TriggerORM)
            .where(TriggerORM.is_active is True)
            .order_by(TriggerORM.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        trigger_orms = result.scalars().all()

        return [self._orm_to_domain(trigger_orm) for trigger_orm in trigger_orms]

    async def get_by_webhook_id(self, webhook_id: str) -> Trigger | None:
        """Get trigger by webhook ID."""
        stmt = select(TriggerORM).where(TriggerORM.webhook_id == webhook_id)
        result = await self.session.execute(stmt)
        trigger_orm = result.scalar_one_or_none()

        if not trigger_orm:
            return None

        return self._orm_to_domain(trigger_orm)

    async def list_cron_triggers_due(self, current_time: datetime) -> list[CronTrigger]:
        """List cron triggers that are due for execution."""
        stmt = (
            select(TriggerORM)
            .where(
                and_(
                    TriggerORM.trigger_type == TriggerType.CRON.value,
                    TriggerORM.is_active is True,
                    TriggerORM.next_run_time <= current_time,
                )
            )
            .order_by(TriggerORM.next_run_time)
        )
        result = await self.session.execute(stmt)
        trigger_orms = result.scalars().all()

        triggers = []
        for trigger_orm in trigger_orms:
            trigger = self._orm_to_domain(trigger_orm)
            if isinstance(trigger, CronTrigger):
                triggers.append(trigger)

        return triggers

    async def update_execution_tracking(
        self, trigger_id: UUID, last_execution_at: datetime, consecutive_failures: int = 0
    ) -> bool:
        """Update trigger execution tracking fields."""
        stmt = (
            update(TriggerORM)
            .where(TriggerORM.id == trigger_id)
            .values(
                last_execution_at=last_execution_at,
                consecutive_failures=consecutive_failures,
                updated_at=datetime.utcnow(),
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()

        return result.rowcount > 0

    async def disable_trigger(self, trigger_id: UUID) -> bool:
        """Disable a trigger."""
        stmt = (
            update(TriggerORM)
            .where(TriggerORM.id == trigger_id)
            .values(is_active=False, updated_at=datetime.utcnow())
        )
        result = await self.session.execute(stmt)
        await self.session.flush()

        return result.rowcount > 0

    async def enable_trigger(self, trigger_id: UUID) -> bool:
        """Enable a trigger."""
        stmt = (
            update(TriggerORM)
            .where(TriggerORM.id == trigger_id)
            .values(is_active=True, updated_at=datetime.utcnow())
        )
        result = await self.session.execute(stmt)
        await self.session.flush()

        return result.rowcount > 0

    def _orm_to_domain(self, trigger_orm: TriggerORM) -> Trigger:
        """Convert ORM model to domain model."""
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
        }

        if trigger_orm.trigger_type == TriggerType.CRON.value:
            return CronTrigger(
                **base_data,
                cron_expression=trigger_orm.cron_expression,
                timezone=trigger_orm.timezone or "UTC",
                next_run_time=trigger_orm.next_run_time,
            )
        elif trigger_orm.trigger_type == TriggerType.WEBHOOK.value:
            from ..domain.enums import WebhookType

            return WebhookTrigger(
                **base_data,
                webhook_id=trigger_orm.webhook_id,
                allowed_methods=trigger_orm.allowed_methods or ["POST"],
                webhook_type=WebhookType(trigger_orm.webhook_type)
                if trigger_orm.webhook_type
                else WebhookType.GENERIC,
                validation_rules=trigger_orm.validation_rules or {},
                webhook_config=trigger_orm.webhook_config,
            )
        else:
            # Fallback to base Trigger
            return Trigger(**base_data)

    def _domain_to_orm(self, trigger: Trigger) -> TriggerORM:
        """Convert domain model to ORM model."""
        orm_data = {
            "id": trigger.id,
            "name": trigger.name,
            "description": trigger.description,
            "agent_id": trigger.agent_id,
            "trigger_type": trigger.trigger_type.value,
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
                {
                    "cron_expression": trigger.cron_expression,
                    "timezone": trigger.timezone,
                    "next_run_time": trigger.next_run_time,
                }
            )
        elif isinstance(trigger, WebhookTrigger):
            orm_data.update(
                {
                    "webhook_id": trigger.webhook_id,
                    "allowed_methods": trigger.allowed_methods,
                    "webhook_type": trigger.webhook_type.value,
                    "validation_rules": trigger.validation_rules,
                    "webhook_config": trigger.webhook_config,
                }
            )

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

    async def list_executions(
        self, limit: int = 100, offset: int = 0, creator_scoped: bool = False
    ) -> list[TriggerExecution]:
        """List all trigger executions in workspace and convert to domain models."""
        execution_orms = await self.list_all(
            creator_scoped=creator_scoped, limit=limit, offset=offset
        )
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
            .where(TriggerExecutionORM.status == status.value)
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
        from sqlalchemy import func

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
        conditions = []
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
        from sqlalchemy import func

        stmt = select(func.count(TriggerExecutionORM.id))

        # Apply filters
        conditions = []
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

    async def get_execution_metrics(self, trigger_id: UUID, hours: int = 24) -> dict[str, Any]:
        """Get execution metrics for a trigger within specified hours."""
        from datetime import timedelta

        from sqlalchemy import case, func

        cutoff_time = datetime.utcnow() - timedelta(hours=hours)

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
            func.avg(TriggerExecutionORM.execution_time_ms).label("avg_execution_time_ms"),
            func.min(TriggerExecutionORM.execution_time_ms).label("min_execution_time_ms"),
            func.max(TriggerExecutionORM.execution_time_ms).label("max_execution_time_ms"),
        ).where(
            and_(
                TriggerExecutionORM.trigger_id == trigger_id,
                TriggerExecutionORM.executed_at >= cutoff_time,
            )
        )

        result = await self.session.execute(stmt)
        row = result.first()

        if not row or row.total_executions == 0:
            return {
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "timeout_executions": 0,
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

        return {
            "total_executions": total,
            "successful_executions": successful,
            "failed_executions": failed,
            "timeout_executions": timeout,
            "success_rate": (successful / total) * 100 if total > 0 else 0.0,
            "failure_rate": ((failed + timeout) / total) * 100 if total > 0 else 0.0,
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

        # Create time buckets
        stmt = (
            select(
                func.date_trunc("hour", TriggerExecutionORM.executed_at).label("time_bucket"),
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
            .group_by(func.date_trunc("hour", TriggerExecutionORM.executed_at))
            .order_by(func.date_trunc("hour", TriggerExecutionORM.executed_at))
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
        return TriggerExecution(
            id=execution_orm.id,
            trigger_id=execution_orm.trigger_id,
            executed_at=execution_orm.executed_at,
            status=ExecutionStatus(execution_orm.status),
            task_id=execution_orm.task_id,
            execution_time_ms=execution_orm.execution_time_ms,
            error_message=execution_orm.error_message,
            trigger_data=execution_orm.trigger_data or {},
            workflow_id=execution_orm.workflow_id,
            run_id=execution_orm.run_id,
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
        )
