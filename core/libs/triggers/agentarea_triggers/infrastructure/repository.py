"""Trigger repository implementation."""

from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from agentarea_common.base.repository import BaseRepository
from sqlalchemy import and_, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..domain.enums import TriggerType, ExecutionStatus
from ..domain.models import Trigger, CronTrigger, WebhookTrigger, TriggerExecution, TriggerCreate, TriggerUpdate
from .orm import TriggerORM, TriggerExecutionORM


class TriggerRepository(BaseRepository[Trigger]):
    """Repository for trigger persistence."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get(self, id: UUID) -> Trigger | None:
        """Get a trigger by ID."""
        stmt = select(TriggerORM).where(TriggerORM.id == id)
        result = await self.session.execute(stmt)
        trigger_orm = result.scalar_one_or_none()
        
        if not trigger_orm:
            return None
        
        return self._orm_to_domain(trigger_orm)
    
    async def list(self) -> List[Trigger]:
        """List all triggers."""
        stmt = select(TriggerORM).order_by(TriggerORM.created_at.desc())
        result = await self.session.execute(stmt)
        trigger_orms = result.scalars().all()
        
        return [self._orm_to_domain(trigger_orm) for trigger_orm in trigger_orms]
    
    async def create(self, entity: Trigger) -> Trigger:
        """Create a new trigger from domain model."""
        trigger_orm = self._domain_to_orm(entity)
        
        self.session.add(trigger_orm)
        await self.session.flush()
        await self.session.refresh(trigger_orm)
        
        return self._orm_to_domain(trigger_orm)
    
    async def update(self, entity: Trigger) -> Trigger:
        """Update an existing trigger."""
        trigger_orm = self._domain_to_orm(entity)
        
        await self.session.merge(trigger_orm)
        await self.session.flush()
        
        return entity
    
    async def delete(self, id: UUID) -> bool:
        """Delete a trigger by ID."""
        stmt = select(TriggerORM).where(TriggerORM.id == id)
        result = await self.session.execute(stmt)
        trigger_orm = result.scalar_one_or_none()
        
        if not trigger_orm:
            return False
        
        await self.session.delete(trigger_orm)
        await self.session.flush()
        return True
    
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
            max_executions_per_hour=trigger_data.max_executions_per_hour,
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
    
    async def list_by_agent(self, agent_id: UUID, limit: int = 100) -> List[Trigger]:
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
    
    async def list_by_type(self, trigger_type: TriggerType, limit: int = 100) -> List[Trigger]:
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
    
    async def list_active_triggers(self, limit: int = 100) -> List[Trigger]:
        """List active triggers."""
        stmt = (
            select(TriggerORM)
            .where(TriggerORM.is_active == True)
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
    
    async def list_cron_triggers_due(self, current_time: datetime) -> List[CronTrigger]:
        """List cron triggers that are due for execution."""
        stmt = (
            select(TriggerORM)
            .where(
                and_(
                    TriggerORM.trigger_type == TriggerType.CRON.value,
                    TriggerORM.is_active == True,
                    TriggerORM.next_run_time <= current_time
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
        self,
        trigger_id: UUID,
        last_execution_at: datetime,
        consecutive_failures: int = 0
    ) -> bool:
        """Update trigger execution tracking fields."""
        stmt = (
            update(TriggerORM)
            .where(TriggerORM.id == trigger_id)
            .values(
                last_execution_at=last_execution_at,
                consecutive_failures=consecutive_failures,
                updated_at=datetime.utcnow()
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
            "max_executions_per_hour": trigger_orm.max_executions_per_hour,
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
                webhook_type=WebhookType(trigger_orm.webhook_type) if trigger_orm.webhook_type else WebhookType.GENERIC,
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
            "max_executions_per_hour": trigger.max_executions_per_hour,
            "failure_threshold": trigger.failure_threshold,
            "consecutive_failures": trigger.consecutive_failures,
            "last_execution_at": trigger.last_execution_at,
        }
        
        if isinstance(trigger, CronTrigger):
            orm_data.update({
                "cron_expression": trigger.cron_expression,
                "timezone": trigger.timezone,
                "next_run_time": trigger.next_run_time,
            })
        elif isinstance(trigger, WebhookTrigger):
            orm_data.update({
                "webhook_id": trigger.webhook_id,
                "allowed_methods": trigger.allowed_methods,
                "webhook_type": trigger.webhook_type.value,
                "validation_rules": trigger.validation_rules,
                "webhook_config": trigger.webhook_config,
            })
        
        return TriggerORM(**orm_data)


class TriggerExecutionRepository(BaseRepository[TriggerExecution]):
    """Repository for trigger execution persistence."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get(self, id: UUID) -> TriggerExecution | None:
        """Get a trigger execution by ID."""
        stmt = select(TriggerExecutionORM).where(TriggerExecutionORM.id == id)
        result = await self.session.execute(stmt)
        execution_orm = result.scalar_one_or_none()
        
        if not execution_orm:
            return None
        
        return self._orm_to_domain(execution_orm)
    
    async def list(self) -> List[TriggerExecution]:
        """List all trigger executions."""
        stmt = select(TriggerExecutionORM).order_by(desc(TriggerExecutionORM.executed_at))
        result = await self.session.execute(stmt)
        execution_orms = result.scalars().all()
        
        return [self._orm_to_domain(execution_orm) for execution_orm in execution_orms]
    
    async def create(self, entity: TriggerExecution) -> TriggerExecution:
        """Create a new trigger execution from domain model."""
        execution_orm = self._domain_to_orm(entity)
        
        self.session.add(execution_orm)
        await self.session.flush()
        await self.session.refresh(execution_orm)
        
        return self._orm_to_domain(execution_orm)
    
    async def update(self, entity: TriggerExecution) -> TriggerExecution:
        """Update an existing trigger execution."""
        execution_orm = self._domain_to_orm(entity)
        
        await self.session.merge(execution_orm)
        await self.session.flush()
        
        return entity
    
    async def delete(self, id: UUID) -> bool:
        """Delete a trigger execution by ID."""
        stmt = select(TriggerExecutionORM).where(TriggerExecutionORM.id == id)
        result = await self.session.execute(stmt)
        execution_orm = result.scalar_one_or_none()
        
        if not execution_orm:
            return False
        
        await self.session.delete(execution_orm)
        await self.session.flush()
        return True
    
    async def list_by_trigger(
        self,
        trigger_id: UUID,
        limit: int = 100,
        offset: int = 0
    ) -> List[TriggerExecution]:
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
        self,
        status: ExecutionStatus,
        limit: int = 100
    ) -> List[TriggerExecution]:
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
        self,
        trigger_id: UUID,
        hours: int = 24,
        limit: int = 100
    ) -> List[TriggerExecution]:
        """Get recent executions for a trigger within specified hours."""
        from datetime import timedelta
        
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        
        stmt = (
            select(TriggerExecutionORM)
            .where(
                and_(
                    TriggerExecutionORM.trigger_id == trigger_id,
                    TriggerExecutionORM.executed_at >= cutoff_time
                )
            )
            .order_by(desc(TriggerExecutionORM.executed_at))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        execution_orms = result.scalars().all()
        
        return [self._orm_to_domain(execution_orm) for execution_orm in execution_orms]
    
    async def count_executions_in_period(
        self,
        trigger_id: UUID,
        start_time: datetime,
        end_time: datetime
    ) -> int:
        """Count executions for a trigger in a specific time period."""
        from sqlalchemy import func
        
        stmt = (
            select(func.count(TriggerExecutionORM.id))
            .where(
                and_(
                    TriggerExecutionORM.trigger_id == trigger_id,
                    TriggerExecutionORM.executed_at >= start_time,
                    TriggerExecutionORM.executed_at <= end_time
                )
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0
    
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