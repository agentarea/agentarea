"""Trigger service for AgentArea platform.

High-level service that orchestrates trigger management by:
1. Handling trigger persistence through TriggerRepository
2. Managing trigger lifecycle and events
3. Validating agent existence before trigger creation
4. Providing CRUD operations for triggers
5. Managing trigger execution history
6. Managing Temporal Schedules for cron triggers
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from agentarea_common.events.broker import EventBroker

from .domain.enums import TriggerType, ExecutionStatus
from .domain.models import (
    Trigger, CronTrigger, WebhookTrigger, TriggerExecution,
    TriggerCreate, TriggerUpdate
)
from .infrastructure.repository import TriggerRepository, TriggerExecutionRepository
from .temporal_schedule_manager import TemporalScheduleManager
from .llm_condition_evaluator import LLMConditionEvaluator, LLMConditionEvaluationError

logger = logging.getLogger(__name__)


class TriggerValidationError(Exception):
    """Raised when trigger validation fails."""
    pass


class TriggerNotFoundError(Exception):
    """Raised when a trigger is not found."""
    pass


class TriggerService:
    """High-level service for trigger management that orchestrates persistence and lifecycle."""

    def __init__(
        self,
        trigger_repository: TriggerRepository,
        trigger_execution_repository: TriggerExecutionRepository,
        event_broker: EventBroker,
        agent_repository: Optional[Any] = None,
        task_service: Optional[Any] = None,
        llm_condition_evaluator: Optional[LLMConditionEvaluator] = None,
        temporal_schedule_manager: Optional[TemporalScheduleManager] = None,
    ):
        """Initialize with repositories, event broker, and optional dependencies."""
        self.trigger_repository = trigger_repository
        self.trigger_execution_repository = trigger_execution_repository
        self.event_broker = event_broker
        self.agent_repository = agent_repository
        self.task_service = task_service
        self.llm_condition_evaluator = llm_condition_evaluator
        self.temporal_schedule_manager = temporal_schedule_manager

    # CRUD Operations

    async def create_trigger(self, trigger_data: TriggerCreate) -> Trigger:
        """Create a new trigger with validation.
        
        Args:
            trigger_data: The trigger creation data
            
        Returns:
            The created trigger
            
        Raises:
            TriggerValidationError: If validation fails
        """
        # Validate agent exists first (fail fast)
        await self._validate_agent_exists(trigger_data.agent_id)
        
        # Validate trigger configuration
        await self._validate_trigger_configuration(trigger_data)
        
        # Create the trigger
        trigger = await self.trigger_repository.create_from_data(trigger_data)
        
        logger.info(f"Created trigger {trigger.id} for agent {trigger.agent_id}")
        
        # TODO: Publish trigger creation event when event system is defined
        
        # Schedule cron trigger if applicable
        if trigger.trigger_type == TriggerType.CRON and isinstance(trigger, CronTrigger):
            try:
                await self.schedule_cron_trigger(trigger)
            except Exception as e:
                logger.error(f"Failed to schedule cron trigger {trigger.id}: {e}")
                # Don't fail the trigger creation if scheduling fails
                # The trigger can be rescheduled later
        
        return trigger

    async def get_trigger(self, trigger_id: UUID) -> Optional[Trigger]:
        """Get a trigger by ID.
        
        Args:
            trigger_id: The unique identifier of the trigger
            
        Returns:
            The trigger if found, None otherwise
        """
        return await self.trigger_repository.get(trigger_id)

    async def update_trigger(self, trigger_id: UUID, trigger_update: TriggerUpdate) -> Trigger:
        """Update an existing trigger with validation.
        
        Args:
            trigger_id: The unique identifier of the trigger
            trigger_update: The trigger update data
            
        Returns:
            The updated trigger
            
        Raises:
            TriggerNotFoundError: If trigger doesn't exist
            TriggerValidationError: If validation fails
        """
        # Check if trigger exists
        existing_trigger = await self.get_trigger(trigger_id)
        if not existing_trigger:
            raise TriggerNotFoundError(f"Trigger {trigger_id} not found")
        
        # Validate update data
        await self._validate_trigger_update(existing_trigger, trigger_update)
        
        # Update the trigger
        updated_trigger = await self.trigger_repository.update_by_id(trigger_id, trigger_update)
        
        if updated_trigger:
            logger.info(f"Updated trigger {trigger_id}")
            # TODO: Publish trigger update event when event system is defined
            
            # Update schedule if it's a cron trigger
            if updated_trigger.trigger_type == TriggerType.CRON and isinstance(updated_trigger, CronTrigger):
                try:
                    # Check if cron expression or active status changed
                    cron_changed = (trigger_update.cron_expression is not None or 
                                   trigger_update.is_active is not None)
                    
                    if cron_changed:
                        await self.temporal_schedule_manager.update_cron_schedule(
                            trigger_id=updated_trigger.id,
                            cron_expression=updated_trigger.cron_expression,
                            timezone=updated_trigger.timezone
                        )
                        logger.info(f"Updated schedule for cron trigger {trigger_id}")
                except Exception as e:
                    logger.error(f"Failed to update schedule for cron trigger {trigger_id}: {e}")
        
        return updated_trigger

    async def delete_trigger(self, trigger_id: UUID) -> bool:
        """Delete a trigger by ID.
        
        Args:
            trigger_id: The unique identifier of the trigger to delete
            
        Returns:
            True if the trigger was successfully deleted, False if not found
        """
        # Check if trigger exists before deletion
        existing_trigger = await self.get_trigger(trigger_id)
        if not existing_trigger:
            return False
        
        # Delete schedule if it's a cron trigger
        if existing_trigger.trigger_type == TriggerType.CRON:
            try:
                await self.temporal_schedule_manager.delete_cron_schedule(trigger_id)
                logger.info(f"Deleted schedule for cron trigger {trigger_id}")
            except Exception as e:
                logger.error(f"Failed to delete schedule for cron trigger {trigger_id}: {e}")
        
        # Delete the trigger (cascade will handle executions)
        success = await self.trigger_repository.delete(trigger_id)
        
        if success:
            logger.info(f"Deleted trigger {trigger_id}")
            # TODO: Publish trigger deletion event when event system is defined
        
        return success

    async def list_triggers(
        self,
        agent_id: Optional[UUID] = None,
        trigger_type: Optional[TriggerType] = None,
        active_only: bool = False,
        limit: int = 100
    ) -> list[Trigger]:
        """List triggers with optional filtering.
        
        Args:
            agent_id: Filter by agent ID
            trigger_type: Filter by trigger type
            active_only: Only return active triggers
            limit: Maximum number of triggers to return
            
        Returns:
            List of triggers matching the criteria
        """
        if agent_id:
            triggers = await self.trigger_repository.list_by_agent(agent_id, limit)
        elif trigger_type:
            triggers = await self.trigger_repository.list_by_type(trigger_type, limit)
        elif active_only:
            triggers = await self.trigger_repository.list_active_triggers(limit)
        else:
            triggers = await self.trigger_repository.list()
        
        return triggers

    # Lifecycle Management

    async def enable_trigger(self, trigger_id: UUID) -> bool:
        """Enable a trigger.
        
        Args:
            trigger_id: The unique identifier of the trigger
            
        Returns:
            True if the trigger was successfully enabled, False if not found
        """
        # Enable trigger in database
        success = await self.trigger_repository.enable_trigger(trigger_id)
        
        if success:
            logger.info(f"Enabled trigger {trigger_id}")
            # TODO: Publish trigger enabled event when event system is defined
            
            # Get trigger to check type
            trigger = await self.get_trigger(trigger_id)
            
            # Enable schedule if it's a cron trigger
            if trigger and trigger.trigger_type == TriggerType.CRON:
                try:
                    await self.temporal_schedule_manager.unpause_cron_schedule(trigger_id)
                    logger.info(f"Unpaused schedule for cron trigger {trigger_id}")
                except Exception as e:
                    logger.error(f"Failed to unpause schedule for cron trigger {trigger_id}: {e}")
        
        return success

    async def disable_trigger(self, trigger_id: UUID) -> bool:
        """Disable a trigger.
        
        Args:
            trigger_id: The unique identifier of the trigger
            
        Returns:
            True if the trigger was successfully disabled, False if not found
        """
        # Disable trigger in database
        success = await self.trigger_repository.disable_trigger(trigger_id)
        
        if success:
            logger.info(f"Disabled trigger {trigger_id}")
            # TODO: Publish trigger disabled event when event system is defined
            
            # Get trigger to check type
            trigger = await self.get_trigger(trigger_id)
            
            # Pause schedule if it's a cron trigger
            if trigger and trigger.trigger_type == TriggerType.CRON:
                try:
                    await self.temporal_schedule_manager.pause_cron_schedule(trigger_id)
                    logger.info(f"Paused schedule for cron trigger {trigger_id}")
                except Exception as e:
                    logger.error(f"Failed to pause schedule for cron trigger {trigger_id}: {e}")
        
        return success

    # Execution History

    async def get_execution_history(
        self,
        trigger_id: UUID,
        limit: int = 100,
        offset: int = 0
    ) -> list[TriggerExecution]:
        """Get execution history for a trigger.
        
        Args:
            trigger_id: The unique identifier of the trigger
            limit: Maximum number of executions to return
            offset: Number of executions to skip
            
        Returns:
            List of trigger executions
        """
        return await self.trigger_execution_repository.list_by_trigger(
            trigger_id, limit, offset
        )

    async def record_execution(
        self,
        trigger_id: UUID,
        status: ExecutionStatus,
        execution_time_ms: int,
        task_id: Optional[UUID] = None,
        error_message: Optional[str] = None,
        trigger_data: Optional[dict[str, Any]] = None,
        workflow_id: Optional[str] = None,
        run_id: Optional[str] = None
    ) -> TriggerExecution:
        """Record a trigger execution.
        
        Args:
            trigger_id: The unique identifier of the trigger
            status: The execution status
            execution_time_ms: Execution time in milliseconds
            task_id: Optional task ID if a task was created
            error_message: Optional error message if execution failed
            trigger_data: Optional trigger data that was processed
            workflow_id: Optional Temporal workflow ID
            run_id: Optional Temporal run ID
            
        Returns:
            The created trigger execution record
        """
        execution = TriggerExecution(
            trigger_id=trigger_id,
            status=status,
            execution_time_ms=execution_time_ms,
            task_id=task_id,
            error_message=error_message,
            trigger_data=trigger_data or {},
            workflow_id=workflow_id,
            run_id=run_id
        )
        
        # Record the execution
        recorded_execution = await self.trigger_execution_repository.create(execution)
        
        # Update trigger execution tracking
        if status == ExecutionStatus.SUCCESS:
            await self.trigger_repository.update_execution_tracking(
                trigger_id, datetime.utcnow(), 0
            )
        else:
            # Get current trigger to increment failure count
            trigger = await self.get_trigger(trigger_id)
            if trigger:
                new_failure_count = trigger.consecutive_failures + 1
                await self.trigger_repository.update_execution_tracking(
                    trigger_id, datetime.utcnow(), new_failure_count
                )
                
                # Auto-disable trigger if failure threshold reached
                if new_failure_count >= trigger.failure_threshold:
                    await self.disable_trigger(trigger_id)
                    logger.warning(
                        f"Auto-disabled trigger {trigger_id} after {new_failure_count} consecutive failures"
                    )
        
        return recorded_execution

    # Temporal Schedule Management

    async def schedule_cron_trigger(self, trigger: CronTrigger) -> None:
        """Schedule a cron trigger using Temporal Schedules.
        
        Args:
            trigger: The cron trigger to schedule
            
        Raises:
            Exception: If scheduling fails
        """
        if not self.temporal_schedule_manager:
            logger.warning(f"Temporal schedule manager not available, cannot schedule trigger {trigger.id}")
            return
        
        try:
            await self.temporal_schedule_manager.create_cron_schedule(
                trigger_id=trigger.id,
                cron_expression=trigger.cron_expression,
                timezone=trigger.timezone
            )
            logger.info(f"Scheduled cron trigger {trigger.id}")
        except Exception as e:
            logger.error(f"Failed to schedule cron trigger {trigger.id}: {e}")
            raise

    async def unschedule_cron_trigger(self, trigger_id: UUID) -> None:
        """Unschedule a cron trigger by deleting its Temporal Schedule.
        
        Args:
            trigger_id: The ID of the trigger to unschedule
            
        Raises:
            Exception: If unscheduling fails
        """
        if not self.temporal_schedule_manager:
            logger.warning(f"Temporal schedule manager not available, cannot unschedule trigger {trigger_id}")
            return
        
        try:
            await self.temporal_schedule_manager.delete_cron_schedule(trigger_id)
            logger.info(f"Unscheduled cron trigger {trigger_id}")
        except Exception as e:
            logger.error(f"Failed to unschedule cron trigger {trigger_id}: {e}")
            raise

    async def update_cron_schedule(self, trigger: CronTrigger) -> None:
        """Update a cron trigger's Temporal Schedule.
        
        Args:
            trigger: The updated cron trigger
            
        Raises:
            Exception: If schedule update fails
        """
        if not self.temporal_schedule_manager:
            logger.warning(f"Temporal schedule manager not available, cannot update schedule for trigger {trigger.id}")
            return
        
        try:
            await self.temporal_schedule_manager.update_cron_schedule(
                trigger_id=trigger.id,
                cron_expression=trigger.cron_expression,
                timezone=trigger.timezone
            )
            logger.info(f"Updated schedule for cron trigger {trigger.id}")
        except Exception as e:
            logger.error(f"Failed to update schedule for cron trigger {trigger.id}: {e}")
            raise

    async def pause_cron_schedule(self, trigger_id: UUID) -> None:
        """Pause a cron trigger's Temporal Schedule.
        
        Args:
            trigger_id: The ID of the trigger to pause
            
        Raises:
            Exception: If pausing fails
        """
        if not self.temporal_schedule_manager:
            logger.warning(f"Temporal schedule manager not available, cannot pause trigger {trigger_id}")
            return
        
        try:
            await self.temporal_schedule_manager.pause_cron_schedule(trigger_id)
            logger.info(f"Paused schedule for cron trigger {trigger_id}")
        except Exception as e:
            logger.error(f"Failed to pause schedule for cron trigger {trigger_id}: {e}")
            raise

    async def unpause_cron_schedule(self, trigger_id: UUID) -> None:
        """Unpause a cron trigger's Temporal Schedule.
        
        Args:
            trigger_id: The ID of the trigger to unpause
            
        Raises:
            Exception: If unpausing fails
        """
        if not self.temporal_schedule_manager:
            logger.warning(f"Temporal schedule manager not available, cannot unpause trigger {trigger_id}")
            return
        
        try:
            await self.temporal_schedule_manager.unpause_cron_schedule(trigger_id)
            logger.info(f"Unpaused schedule for cron trigger {trigger_id}")
        except Exception as e:
            logger.error(f"Failed to unpause schedule for cron trigger {trigger_id}: {e}")
            raise

    async def get_cron_schedule_info(self, trigger_id: UUID) -> Optional[dict]:
        """Get information about a cron trigger's Temporal Schedule.
        
        Args:
            trigger_id: The ID of the trigger
            
        Returns:
            Dictionary with schedule information, or None if not found
        """
        if not self.temporal_schedule_manager:
            logger.warning(f"Temporal schedule manager not available, cannot get schedule info for trigger {trigger_id}")
            return None
        
        try:
            return await self.temporal_schedule_manager.get_schedule_info(trigger_id)
        except Exception as e:
            logger.error(f"Failed to get schedule info for cron trigger {trigger_id}: {e}")
            return None

    # Validation Methods

    async def _validate_agent_exists(self, agent_id: UUID) -> None:
        """Validate that the agent exists before processing triggers.
        
        Args:
            agent_id: The agent ID to validate
            
        Raises:
            TriggerValidationError: If agent doesn't exist or agent_repository is not available
        """
        if not self.agent_repository:
            logger.warning("Agent repository not available - skipping agent validation")
            return

        agent = await self.agent_repository.get(agent_id)
        if not agent:
            raise TriggerValidationError(f"Agent with ID {agent_id} does not exist")

    async def _validate_trigger_configuration(self, trigger_data: TriggerCreate) -> None:
        """Validate trigger configuration based on type.
        
        Args:
            trigger_data: The trigger creation data
            
        Raises:
            TriggerValidationError: If configuration is invalid
        """
        # Basic validation
        if not trigger_data.name or not trigger_data.name.strip():
            raise TriggerValidationError("Trigger name is required")
        
        if not trigger_data.created_by or not trigger_data.created_by.strip():
            raise TriggerValidationError("Trigger created_by is required")
        
        # Type-specific validation
        if trigger_data.trigger_type == TriggerType.CRON:
            await self._validate_cron_configuration(trigger_data)
        elif trigger_data.trigger_type == TriggerType.WEBHOOK:
            await self._validate_webhook_configuration(trigger_data)

    async def _validate_cron_configuration(self, trigger_data: TriggerCreate) -> None:
        """Validate cron trigger configuration.
        
        Args:
            trigger_data: The trigger creation data
            
        Raises:
            TriggerValidationError: If cron configuration is invalid
        """
        if not trigger_data.cron_expression:
            raise TriggerValidationError("Cron expression is required for CRON triggers")
        
        # Basic cron expression validation
        parts = trigger_data.cron_expression.strip().split()
        if len(parts) not in [5, 6]:
            raise TriggerValidationError("Cron expression must have 5 or 6 parts")
        
        # Validate timezone
        if not trigger_data.timezone or not trigger_data.timezone.strip():
            raise TriggerValidationError("Timezone is required for CRON triggers")

    async def _validate_webhook_configuration(self, trigger_data: TriggerCreate) -> None:
        """Validate webhook trigger configuration.
        
        Args:
            trigger_data: The trigger creation data
            
        Raises:
            TriggerValidationError: If webhook configuration is invalid
        """
        if not trigger_data.webhook_id:
            raise TriggerValidationError("Webhook ID is required for WEBHOOK triggers")
        
        # Validate HTTP methods
        if not trigger_data.allowed_methods:
            raise TriggerValidationError("At least one HTTP method must be allowed")
        
        valid_methods = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
        for method in trigger_data.allowed_methods:
            if method.upper() not in valid_methods:
                raise TriggerValidationError(f"Invalid HTTP method: {method}")

    async def _validate_trigger_update(
        self,
        existing_trigger: Trigger,
        trigger_update: TriggerUpdate
    ) -> None:
        """Validate trigger update data.
        
        Args:
            existing_trigger: The existing trigger
            trigger_update: The update data
            
        Raises:
            TriggerValidationError: If update is invalid
        """
        # Validate name if provided
        if trigger_update.name is not None and not trigger_update.name.strip():
            raise TriggerValidationError("Trigger name cannot be empty")
        
        # Type-specific validation
        if isinstance(existing_trigger, CronTrigger):
            if trigger_update.cron_expression is not None:
                parts = trigger_update.cron_expression.strip().split()
                if len(parts) not in [5, 6]:
                    raise TriggerValidationError("Cron expression must have 5 or 6 parts")
        
        elif isinstance(existing_trigger, WebhookTrigger):
            if trigger_update.allowed_methods is not None:
                if not trigger_update.allowed_methods:
                    raise TriggerValidationError("At least one HTTP method must be allowed")
                
                valid_methods = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
                for method in trigger_update.allowed_methods:
                    if method.upper() not in valid_methods:
                        raise TriggerValidationError(f"Invalid HTTP method: {method}")

    # Utility Methods

    async def get_trigger_by_webhook_id(self, webhook_id: str) -> Optional[WebhookTrigger]:
        """Get a webhook trigger by webhook ID.
        
        Args:
            webhook_id: The webhook ID
            
        Returns:
            The webhook trigger if found, None otherwise
        """
        trigger = await self.trigger_repository.get_by_webhook_id(webhook_id)
        if trigger and isinstance(trigger, WebhookTrigger):
            return trigger
        return None

    async def list_cron_triggers_due(self, current_time: Optional[datetime] = None) -> list[CronTrigger]:
        """List cron triggers that are due for execution.
        
        Args:
            current_time: The current time (defaults to now)
            
        Returns:
            List of cron triggers due for execution
        """
        if current_time is None:
            current_time = datetime.utcnow()
        
        return await self.trigger_repository.list_cron_triggers_due(current_time)

    async def get_recent_executions(
        self,
        trigger_id: UUID,
        hours: int = 24,
        limit: int = 100
    ) -> list[TriggerExecution]:
        """Get recent executions for a trigger.
        
        Args:
            trigger_id: The trigger ID
            hours: Number of hours to look back
            limit: Maximum number of executions to return
            
        Returns:
            List of recent trigger executions
        """
        return await self.trigger_execution_repository.get_recent_executions(
            trigger_id, hours, limit
        )

    async def count_executions_in_period(
        self,
        trigger_id: UUID,
        start_time: datetime,
        end_time: datetime
    ) -> int:
        """Count executions for a trigger in a specific time period.
        
        Args:
            trigger_id: The trigger ID
            start_time: Start of the time period
            end_time: End of the time period
            
        Returns:
            Number of executions in the period
        """
        return await self.trigger_execution_repository.count_executions_in_period(
            trigger_id, start_time, end_time
        )

    async def execute_trigger(self, trigger_id: UUID, trigger_data: Dict[str, Any]) -> TriggerExecution:
        """Execute a trigger.
        
        Args:
            trigger_id: The ID of the trigger to execute
            trigger_data: Additional data for trigger execution
            
        Returns:
            Execution record
            
        Raises:
            TriggerNotFoundError: If trigger doesn't exist
        """
        # Get the trigger
        trigger = await self.get_trigger(trigger_id)
        if not trigger:
            raise TriggerNotFoundError(f"Trigger {trigger_id} not found")
        
        # Check if trigger is active
        if not trigger.is_active:
            logger.warning(f"Attempted to execute inactive trigger {trigger_id}")
            return await self._record_execution_failure(
                trigger_id, 
                "Trigger is inactive", 
                trigger_data
            )
        
        # Rate limiting is handled at infrastructure layer (ingress/load balancer)
        
        # Start execution timing
        start_time = time.time()
        
        try:
            # Evaluate conditions if any
            if trigger.conditions:
                conditions_met = await self.evaluate_trigger_conditions(trigger, trigger_data)
                if not conditions_met:
                    logger.info(f"Trigger {trigger_id} conditions not met, skipping execution")
                    return await self._record_execution_failure(
                        trigger_id,
                        "Trigger conditions not met",
                        trigger_data
                    )
            
            # Create task from trigger
            task_id = None
            if self.task_service:
                # Build task parameters
                task_params = await self._build_task_parameters(trigger, trigger_data)
                
                # Create task
                task = await self.task_service.create_task_from_params(
                    title=f"Trigger: {trigger.name}",
                    description=trigger.description or f"Execution of trigger {trigger.name}",
                    query=trigger.description or f"Execute trigger {trigger.name}",
                    user_id=trigger.created_by,
                    agent_id=trigger.agent_id,
                    task_parameters=task_params
                )
                
                task_id = task.id
                logger.info(f"Created task {task_id} from trigger {trigger_id}")
            else:
                logger.warning(f"Task service not available, skipping task creation for trigger {trigger_id}")
            
            # Calculate execution time
            execution_time_ms = int((time.time() - start_time) * 1000)
            
            # Record successful execution
            execution = await self._record_execution_success(
                trigger_id, 
                execution_time_ms, 
                task_id, 
                trigger_data
            )
            
            # Update trigger execution tracking
            trigger.record_execution_success()
            await self.trigger_repository.update(trigger)
            
            return execution
            
        except Exception as e:
            # Calculate execution time
            execution_time_ms = int((time.time() - start_time) * 1000)
            
            # Log error
            logger.error(f"Error executing trigger {trigger_id}: {e}")
            
            # Record failed execution
            execution = await self._record_execution_failure(
                trigger_id, 
                str(e), 
                trigger_data, 
                execution_time_ms
            )
            
            # Update trigger execution tracking
            trigger.record_execution_failure()
            await self.trigger_repository.update(trigger)
            
            # Check if trigger should be disabled due to failures
            if trigger.should_disable_due_to_failures():
                logger.warning(f"Disabling trigger {trigger_id} due to consecutive failures")
                await self.disable_trigger(trigger_id)
            
            return execution
    
    async def _record_execution_success(
        self, 
        trigger_id: UUID, 
        execution_time_ms: int, 
        task_id: Optional[UUID] = None,
        trigger_data: Optional[Dict[str, Any]] = None
    ) -> TriggerExecution:
        """Record successful trigger execution.
        
        Args:
            trigger_id: The trigger ID
            execution_time_ms: Execution time in milliseconds
            task_id: Optional task ID if a task was created
            trigger_data: Optional trigger data
            
        Returns:
            Execution record
        """
        return await self.record_execution(
            trigger_id=trigger_id,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=execution_time_ms,
            task_id=task_id,
            trigger_data=trigger_data or {}
        )
    
    async def _record_execution_failure(
        self, 
        trigger_id: UUID, 
        error_message: str,
        trigger_data: Optional[Dict[str, Any]] = None,
        execution_time_ms: int = 0
    ) -> TriggerExecution:
        """Record failed trigger execution.
        
        Args:
            trigger_id: The trigger ID
            error_message: Error message
            trigger_data: Optional trigger data
            execution_time_ms: Execution time in milliseconds
            
        Returns:
            Execution record
        """
        return await self.record_execution(
            trigger_id=trigger_id,
            status=ExecutionStatus.FAILED,
            execution_time_ms=execution_time_ms,
            error_message=error_message,
            trigger_data=trigger_data or {}
        )
    
    async def _build_task_parameters(
        self, 
        trigger: Trigger, 
        trigger_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build task parameters from trigger and execution data using LLM extraction.
        
        Args:
            trigger: The trigger
            trigger_data: Trigger execution data
            
        Returns:
            Task parameters
        """
        # Start with trigger's task parameters
        params = dict(trigger.task_parameters)
        
        # Add trigger metadata
        params.update({
            "trigger_id": str(trigger.id),
            "trigger_type": trigger.trigger_type.value,
            "trigger_name": trigger.name,
            "execution_time": datetime.utcnow().isoformat(),
        })
        
        # Add trigger data
        if trigger_data:
            params["trigger_data"] = trigger_data
        
        # Use LLM to extract additional parameters if instruction is provided
        llm_instruction = trigger.task_parameters.get("llm_parameter_extraction")
        if llm_instruction and self.llm_condition_evaluator:
            try:
                trigger_context = {
                    "trigger_id": str(trigger.id),
                    "trigger_name": trigger.name,
                    "trigger_type": trigger.trigger_type.value,
                    "agent_id": str(trigger.agent_id),
                }
                
                llm_params = await self.extract_task_parameters_with_llm(
                    instruction=llm_instruction,
                    event_data=trigger_data,
                    trigger_context=trigger_context
                )
                
                # Merge LLM-extracted parameters (don't override existing ones)
                for key, value in llm_params.items():
                    if key not in params:
                        params[key] = value
                
                logger.info(f"Enhanced task parameters with LLM extraction for trigger {trigger.id}")
                
            except Exception as e:
                logger.warning(f"LLM parameter extraction failed for trigger {trigger.id}: {e}")
                # Continue with basic parameters
        
        return params

    async def evaluate_trigger_conditions(
        self, 
        trigger: Trigger, 
        event_data: Dict[str, Any]
    ) -> bool:
        """Evaluate trigger conditions against event data using LLM-powered evaluation.
        
        Args:
            trigger: The trigger to evaluate
            event_data: Event data to evaluate against
            
        Returns:
            True if conditions are met, False otherwise
        """
        if not trigger.conditions:
            return True
        
        try:
            # Use LLM condition evaluator if available
            if self.llm_condition_evaluator:
                # Build trigger context for evaluation
                trigger_context = {
                    "trigger_id": str(trigger.id),
                    "trigger_name": trigger.name,
                    "trigger_type": trigger.trigger_type.value,
                    "agent_id": str(trigger.agent_id),
                }
                
                # Evaluate conditions using LLM
                return await self.llm_condition_evaluator.evaluate_condition(
                    condition=trigger.conditions,
                    event_data=event_data,
                    trigger_context=trigger_context
                )
            
            # Fallback to simple rule-based evaluation if no LLM evaluator
            return await self._evaluate_simple_conditions(trigger.conditions, event_data)
            
        except LLMConditionEvaluationError as e:
            logger.error(f"LLM condition evaluation failed for trigger {trigger.id}: {e}")
            # Fallback to simple evaluation on LLM failure
            try:
                return await self._evaluate_simple_conditions(trigger.conditions, event_data)
            except Exception as fallback_error:
                logger.error(f"Fallback condition evaluation also failed: {fallback_error}")
                # Default to True to avoid blocking execution on condition evaluation errors
                return True
            
        except Exception as e:
            logger.error(f"Error evaluating conditions for trigger {trigger.id}: {e}")
            # Default to True to avoid blocking execution on condition evaluation errors
            return True

    def _get_nested_value(self, data: Dict[str, Any], field_path: str) -> Any:
        """Get nested value from dictionary using dot notation.
        
        Args:
            data: Dictionary to search in
            field_path: Dot-separated path (e.g., "request.body.message_type")
            
        Returns:
            The value at the path, or None if not found
        """
        try:
            value = data
            for key in field_path.split('.'):
                if isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    return None
            return value
        except Exception:
            return None

    async def _evaluate_simple_conditions(
        self,
        conditions: Dict[str, Any],
        event_data: Dict[str, Any]
    ) -> bool:
        """Evaluate simple rule-based conditions as fallback.
        
        Args:
            conditions: Condition configuration
            event_data: Event data to evaluate
            
        Returns:
            True if conditions are met, False otherwise
        """
        try:
            # Check for simple field matching conditions
            if "field_matches" in conditions:
                field_matches = conditions["field_matches"]
                for field_path, expected_value in field_matches.items():
                    actual_value = self._get_nested_value(event_data, field_path)
                    if actual_value != expected_value:
                        logger.debug(f"Condition not met: {field_path} = {actual_value}, expected {expected_value}")
                        return False
            
            # Check for time-based conditions (for cron triggers)
            if "time_conditions" in conditions:
                time_conditions = conditions["time_conditions"]
                current_time = datetime.utcnow()
                
                if "hour_range" in time_conditions:
                    hour_range = time_conditions["hour_range"]
                    if not (hour_range[0] <= current_time.hour <= hour_range[1]):
                        logger.debug(f"Time condition not met: hour {current_time.hour} not in range {hour_range}")
                        return False
                
                if "weekdays_only" in time_conditions and time_conditions["weekdays_only"]:
                    if current_time.weekday() >= 5:  # Saturday = 5, Sunday = 6
                        logger.debug("Time condition not met: weekends excluded")
                        return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error in simple condition evaluation: {e}")
            return True

    async def validate_condition_syntax(self, conditions: Dict[str, Any]) -> List[str]:
        """Validate trigger condition syntax and return any errors.
        
        Args:
            conditions: Condition configuration to validate
            
        Returns:
            List of validation error messages (empty if valid)
        """
        if not conditions:
            return []
        
        try:
            if self.llm_condition_evaluator:
                return await self.llm_condition_evaluator.validate_condition_syntax(conditions)
            else:
                # Basic validation for simple conditions
                errors = []
                
                if "field_matches" in conditions:
                    field_matches = conditions["field_matches"]
                    if not isinstance(field_matches, dict):
                        errors.append("field_matches must be a dictionary")
                
                if "time_conditions" in conditions:
                    time_conditions = conditions["time_conditions"]
                    if not isinstance(time_conditions, dict):
                        errors.append("time_conditions must be a dictionary")
                    else:
                        if "hour_range" in time_conditions:
                            hour_range = time_conditions["hour_range"]
                            if not isinstance(hour_range, list) or len(hour_range) != 2:
                                errors.append("hour_range must be a list of two integers")
                            elif not all(isinstance(h, int) and 0 <= h <= 23 for h in hour_range):
                                errors.append("hour_range values must be integers between 0 and 23")
                
                return errors
                
        except Exception as e:
            return [f"Validation error: {e}"]

    async def extract_task_parameters_with_llm(
        self,
        instruction: str,
        event_data: Dict[str, Any],
        trigger_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Extract task parameters from event data using LLM.
        
        Args:
            instruction: Natural language instruction for parameter extraction
            event_data: Event data to extract parameters from
            trigger_context: Optional trigger context
            
        Returns:
            Dictionary of extracted parameters
            
        Raises:
            LLMConditionEvaluationError: If parameter extraction fails
        """
        if not self.llm_condition_evaluator:
            logger.warning("LLM condition evaluator not available, using basic parameter extraction")
            return {
                "event_data": event_data,
                "instruction": instruction,
                "extracted_via": "basic_fallback"
            }
        
        try:
            return await self.llm_condition_evaluator.extract_task_parameters(
                instruction=instruction,
                event_data=event_data,
                trigger_context=trigger_context
            )
        except LLMConditionEvaluationError as e:
            logger.error(f"LLM parameter extraction failed: {e}")
            # Fallback to basic parameter extraction
            return {
                "event_data": event_data,
                "instruction": instruction,
                "error": str(e),
                "extracted_via": "error_fallback"
            }