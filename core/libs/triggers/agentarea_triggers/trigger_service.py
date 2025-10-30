"""Trigger service for AgentArea platform.

High-level service that orchestrates trigger management by:
1. Handling trigger persistence through TriggerRepository
2. Managing trigger lifecycle and events
3. Validating agent existence before trigger creation
4. Providing CRUD operations for triggers
5. Managing trigger execution history
6. Managing Temporal Schedules for cron triggers
"""

import time
from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_common.events.broker import EventBroker

from .domain.enums import ExecutionStatus, TriggerType
from .domain.models import (
    CronTrigger,
    Trigger,
    TriggerCreate,
    TriggerExecution,
    TriggerUpdate,
    WebhookTrigger,
)
from .infrastructure.repository import TriggerExecutionRepository, TriggerRepository
from .llm_condition_evaluator import LLMConditionEvaluationError, LLMConditionEvaluator
from .logging_utils import (
    DependencyUnavailableError,
    TriggerExecutionError,
    TriggerLogger,
    TriggerNotFoundError,
    TriggerValidationError,
    generate_correlation_id,
    set_correlation_id,
)
from .temporal_schedule_manager import TemporalScheduleManager

logger = TriggerLogger(__name__)


# Error classes moved to logging_utils.py for consistency


class TriggerService:
    """High-level service for trigger management that orchestrates persistence and lifecycle."""

    def __init__(
        self,
        repository_factory: Any,  # RepositoryFactory type
        event_broker: EventBroker,
        task_service: Any | None = None,
        llm_condition_evaluator: LLMConditionEvaluator | None = None,
        temporal_schedule_manager: TemporalScheduleManager | None = None,
    ):
        """Initialize with repository factory, event broker, and optional dependencies."""
        # Create repositories using factory
        self.trigger_repository = repository_factory.create_repository(TriggerRepository)
        self.trigger_execution_repository = repository_factory.create_repository(
            TriggerExecutionRepository
        )

        self.repository_factory = repository_factory
        self.event_broker = event_broker
        self.task_service = task_service
        self.llm_condition_evaluator = llm_condition_evaluator
        self.temporal_schedule_manager = temporal_schedule_manager

        # Create agent repository using factory for validation
        try:
            from agentarea_agents.infrastructure.repository import AgentRepository

            self.agent_repository = repository_factory.create_repository(AgentRepository)
        except ImportError:
            self.agent_repository = None

    # CRUD Operations

    async def create_trigger(self, trigger_data: TriggerCreate) -> Trigger:
        """Create a new trigger with validation.

        Args:
            trigger_data: The trigger creation data

        Returns:
            The created trigger

        Raises:
            TriggerValidationError: If validation fails
            DependencyUnavailableError: If required dependencies are unavailable
        """
        correlation_id = generate_correlation_id()
        set_correlation_id(correlation_id)

        try:
            logger.info(
                f"Creating trigger '{trigger_data.name}' for agent {trigger_data.agent_id}",
                trigger_type=trigger_data.trigger_type.value,
                agent_id=trigger_data.agent_id,
            )

            # Validate agent exists first (fail fast)
            await self._validate_agent_exists(trigger_data.agent_id)

            # Validate trigger configuration
            await self._validate_trigger_configuration(trigger_data)

            # Create the trigger
            trigger = await self.trigger_repository.create_from_model(trigger_data)

            logger.info(
                f"Successfully created trigger '{trigger.name}'",
                trigger_id=trigger.id,
                agent_id=trigger.agent_id,
                trigger_type=trigger.trigger_type.value,
            )

            # TODO: Publish trigger creation event when event system is defined

            # Schedule cron trigger if applicable
            if trigger.trigger_type == TriggerType.CRON and isinstance(trigger, CronTrigger):
                try:
                    await self.schedule_cron_trigger(trigger)
                    logger.info(
                        "Successfully scheduled cron trigger",
                        trigger_id=trigger.id,
                        cron_expression=trigger.cron_expression,
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to schedule cron trigger: {e}",
                        trigger_id=trigger.id,
                        cron_expression=trigger.cron_expression,
                    )
                    # Don't fail the trigger creation if scheduling fails
                    # The trigger can be rescheduled later

            return trigger

        except TriggerValidationError:
            logger.error(
                f"Trigger validation failed for '{trigger_data.name}'",
                agent_id=trigger_data.agent_id,
                trigger_type=trigger_data.trigger_type.value,
            )
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error creating trigger '{trigger_data.name}': {e}",
                agent_id=trigger_data.agent_id,
                trigger_type=trigger_data.trigger_type.value,
            )
            raise TriggerExecutionError(
                f"Failed to create trigger: {e}",
                correlation_id=correlation_id,
                trigger_name=trigger_data.name,
                agent_id=str(trigger_data.agent_id),
            ) from None

    async def get_trigger(self, trigger_id: UUID) -> Trigger | None:
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
            if updated_trigger.trigger_type == TriggerType.CRON and isinstance(
                updated_trigger, CronTrigger
            ):
                try:
                    # Check if cron expression or active status changed
                    cron_changed = (
                        trigger_update.cron_expression is not None
                        or trigger_update.is_active is not None
                    )

                    if cron_changed:
                        await self.temporal_schedule_manager.update_cron_schedule(
                            trigger_id=updated_trigger.id,
                            cron_expression=updated_trigger.cron_expression,
                            timezone=updated_trigger.timezone,
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
        agent_id: UUID | None = None,
        trigger_type: TriggerType | None = None,
        active_only: bool = False,
        creator_scoped: bool = False,
        limit: int = 100,
    ) -> list[Trigger]:
        """List triggers with optional filtering.

        Args:
            agent_id: Filter by agent ID
            trigger_type: Filter by trigger type
            active_only: Only return active triggers
            creator_scoped: If True, only return triggers created by current user
            limit: Maximum number of triggers to return

        Returns:
            List of triggers matching the criteria
        """
        # Build filters for the repository
        filters = {}
        if agent_id:
            filters["agent_id"] = agent_id
        if trigger_type:
            filters["trigger_type"] = trigger_type
        if active_only:
            filters["is_active"] = True

        # Use the repository's list_all method with creator_scoped parameter
        if hasattr(self.trigger_repository, "list_all"):
            triggers = await self.trigger_repository.list_all(
                creator_scoped=creator_scoped, limit=limit, **filters
            )
        else:
            # Fallback for repositories that don't support workspace scoping
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
        self, trigger_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[TriggerExecution]:
        """Get execution history for a trigger.

        Args:
            trigger_id: The unique identifier of the trigger
            limit: Maximum number of executions to return
            offset: Number of executions to skip

        Returns:
            List of trigger executions
        """
        return await self.trigger_execution_repository.list_by_trigger(trigger_id, limit, offset)

    async def record_execution(
        self,
        trigger_id: UUID,
        status: ExecutionStatus,
        execution_time_ms: int,
        task_id: UUID | None = None,
        error_message: str | None = None,
        trigger_data: dict[str, Any] | None = None,
        workflow_id: str | None = None,
        run_id: str | None = None,
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

        Raises:
            TriggerExecutionError: If execution recording fails
        """
        try:
            logger.info(
                f"Recording trigger execution with status {status.value}",
                trigger_id=trigger_id,
                status=status.value,
                execution_time_ms=execution_time_ms,
                task_id=task_id,
                workflow_id=workflow_id,
                run_id=run_id,
            )

            execution = TriggerExecution(
                trigger_id=trigger_id,
                status=status,
                execution_time_ms=execution_time_ms,
                task_id=task_id,
                error_message=error_message,
                trigger_data=trigger_data or {},
                workflow_id=workflow_id,
                run_id=run_id,
            )

            # Record the execution
            recorded_execution = await self.trigger_execution_repository.create(execution)

            logger.info(
                "Successfully recorded trigger execution",
                trigger_id=trigger_id,
                execution_id=recorded_execution.id,
                status=status.value,
            )

            # Update trigger execution tracking and handle automatic disabling
            try:
                await self._update_trigger_execution_tracking(trigger_id, status)
            except Exception as tracking_error:
                # Log tracking error but don't fail the execution recording
                logger.error(
                    f"Failed to update trigger execution tracking: {tracking_error}",
                    trigger_id=trigger_id,
                    execution_id=recorded_execution.id,
                )

            return recorded_execution

        except Exception as e:
            error_msg = f"Failed to record trigger execution: {e}"
            logger.error(
                error_msg,
                trigger_id=trigger_id,
                status=status.value,
                execution_time_ms=execution_time_ms,
            )
            raise TriggerExecutionError(
                error_msg, trigger_id=str(trigger_id), status=status.value, original_error=str(e)
            ) from None

    async def _update_trigger_execution_tracking(
        self, trigger_id: UUID, status: ExecutionStatus
    ) -> None:
        """Update trigger execution tracking and handle automatic disabling.

        Args:
            trigger_id: The trigger ID
            status: The execution status
        """
        # Get the trigger
        trigger = await self.get_trigger(trigger_id)
        if not trigger:
            logger.warning(f"Trigger {trigger_id} not found for execution tracking update")
            return

        # Update execution tracking
        if status == ExecutionStatus.SUCCESS:
            trigger.record_execution_success()
        else:
            trigger.record_execution_failure()

        # Update trigger in database
        await self.trigger_repository.update(trigger)

        # Check if trigger should be disabled due to consecutive failures
        if trigger.should_disable_due_to_failures():
            logger.warning(
                f"Trigger {trigger_id} reached failure threshold ({trigger.failure_threshold}), "
                f"disabling trigger after {trigger.consecutive_failures} consecutive failures"
            )
            await self.disable_trigger(trigger_id)

            # Publish trigger auto-disabled event
            await self._publish_trigger_auto_disabled_event(
                trigger_id, trigger.consecutive_failures
            )

    async def _publish_trigger_auto_disabled_event(
        self, trigger_id: UUID, consecutive_failures: int
    ) -> None:
        """Publish event when trigger is automatically disabled due to failures.

        Args:
            trigger_id: The trigger ID that was disabled
            consecutive_failures: Number of consecutive failures that caused the disable
        """
        try:
            await self.event_broker.publish(
                event_type="trigger.auto_disabled",
                data={
                    "trigger_id": str(trigger_id),
                    "consecutive_failures": consecutive_failures,
                    "disabled_at": datetime.utcnow().isoformat(),
                    "reason": "consecutive_failures_threshold_exceeded",
                },
            )
            logger.info(f"Published auto-disabled event for trigger {trigger_id}")
        except Exception as e:
            logger.error(f"Failed to publish auto-disabled event for trigger {trigger_id}: {e}")

    async def reset_trigger_failure_count(self, trigger_id: UUID) -> bool:
        """Reset the consecutive failure count for a trigger.

        This can be used to manually reset a trigger's failure count without
        waiting for a successful execution.

        Args:
            trigger_id: The trigger ID to reset

        Returns:
            True if reset was successful, False if trigger not found
        """
        trigger = await self.get_trigger(trigger_id)
        if not trigger:
            return False

        # Reset failure count
        trigger.consecutive_failures = 0
        trigger.updated_at = datetime.utcnow()

        # Update in database
        await self.trigger_repository.update(trigger)

        logger.info(f"Reset failure count for trigger {trigger_id}")
        return True

    async def get_trigger_safety_status(self, trigger_id: UUID) -> dict[str, Any] | None:
        """Get safety status information for a trigger.

        Args:
            trigger_id: The trigger ID

        Returns:
            Dictionary with safety status information, or None if trigger not found
        """
        trigger = await self.get_trigger(trigger_id)
        if not trigger:
            return None

        return {
            "trigger_id": str(trigger_id),
            "consecutive_failures": trigger.consecutive_failures,
            "failure_threshold": trigger.failure_threshold,
            "failures_until_disable": max(
                0, trigger.failure_threshold - trigger.consecutive_failures
            ),
            "is_at_risk": trigger.consecutive_failures
            >= (trigger.failure_threshold * 0.8),  # 80% threshold
            "should_disable": trigger.should_disable_due_to_failures(),
            "last_execution_at": trigger.last_execution_at.isoformat()
            if trigger.last_execution_at
            else None,
        }

    # Temporal Schedule Management

    async def schedule_cron_trigger(self, trigger: CronTrigger) -> None:
        """Schedule a cron trigger using Temporal Schedules.

        Args:
            trigger: The cron trigger to schedule

        Raises:
            DependencyUnavailableError: If temporal_schedule_manager is not available
            TriggerExecutionError: If scheduling fails
        """
        if not self.temporal_schedule_manager:
            error_msg = "Temporal schedule manager not available - cannot schedule cron trigger"
            logger.error(error_msg, trigger_id=trigger.id)
            raise DependencyUnavailableError(
                error_msg, dependency="temporal_schedule_manager", trigger_id=str(trigger.id)
            )

        try:
            logger.info(
                "Scheduling cron trigger",
                trigger_id=trigger.id,
                cron_expression=trigger.cron_expression,
                timezone=trigger.timezone,
            )

            await self.temporal_schedule_manager.create_cron_schedule(
                trigger_id=trigger.id,
                cron_expression=trigger.cron_expression,
                timezone=trigger.timezone,
            )

            logger.info(
                "Successfully scheduled cron trigger",
                trigger_id=trigger.id,
                cron_expression=trigger.cron_expression,
            )

        except Exception as e:
            error_msg = f"Failed to schedule cron trigger: {e}"
            logger.error(
                error_msg,
                trigger_id=trigger.id,
                cron_expression=trigger.cron_expression,
                timezone=trigger.timezone,
            )
            raise TriggerExecutionError(
                error_msg,
                trigger_id=str(trigger.id),
                cron_expression=trigger.cron_expression,
                original_error=str(e),
            ) from None

    async def unschedule_cron_trigger(self, trigger_id: UUID) -> None:
        """Unschedule a cron trigger by deleting its Temporal Schedule.

        Args:
            trigger_id: The ID of the trigger to unschedule

        Raises:
            Exception: If unscheduling fails
        """
        if not self.temporal_schedule_manager:
            logger.warning(
                f"Temporal schedule manager not available, cannot unschedule trigger {trigger_id}"
            )
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
            logger.warning(
                f"Temporal schedule manager not available, cannot update schedule for trigger {trigger.id}"
            )
            return

        try:
            await self.temporal_schedule_manager.update_cron_schedule(
                trigger_id=trigger.id,
                cron_expression=trigger.cron_expression,
                timezone=trigger.timezone,
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
            logger.warning(
                f"Temporal schedule manager not available, cannot pause trigger {trigger_id}"
            )
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
            logger.warning(
                f"Temporal schedule manager not available, cannot unpause trigger {trigger_id}"
            )
            return

        try:
            await self.temporal_schedule_manager.unpause_cron_schedule(trigger_id)
            logger.info(f"Unpaused schedule for cron trigger {trigger_id}")
        except Exception as e:
            logger.error(f"Failed to unpause schedule for cron trigger {trigger_id}: {e}")
            raise

    async def get_cron_schedule_info(self, trigger_id: UUID) -> dict | None:
        """Get information about a cron trigger's Temporal Schedule.

        Args:
            trigger_id: The ID of the trigger

        Returns:
            Dictionary with schedule information, or None if not found
        """
        if not self.temporal_schedule_manager:
            logger.warning(
                f"Temporal schedule manager not available, cannot get schedule info for trigger {trigger_id}"
            )
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
            TriggerValidationError: If agent doesn't exist
            DependencyUnavailableError: If agent_repository is not available
        """
        if not self.agent_repository:
            error_msg = "Agent repository not available - cannot validate agent existence"
            logger.error(error_msg, agent_id=agent_id)
            raise DependencyUnavailableError(
                error_msg, dependency="agent_repository", agent_id=str(agent_id)
            )

        try:
            agent = await self.agent_repository.get(agent_id)
            if not agent:
                error_msg = f"Agent with ID {agent_id} does not exist"
                logger.error(error_msg, agent_id=agent_id)
                raise TriggerValidationError(error_msg, agent_id=str(agent_id))

            logger.debug("Agent validation successful", agent_id=agent_id)

        except Exception as e:
            if isinstance(e, TriggerValidationError | DependencyUnavailableError):
                raise

            error_msg = f"Error validating agent existence: {e}"
            logger.error(error_msg, agent_id=agent_id)
            raise DependencyUnavailableError(
                error_msg,
                dependency="agent_repository",
                agent_id=str(agent_id),
                original_error=str(e),
            ) from e

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
        self, existing_trigger: Trigger, trigger_update: TriggerUpdate
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

    async def get_trigger_by_webhook_id(self, webhook_id: str) -> WebhookTrigger | None:
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

    async def list_cron_triggers_due(
        self, current_time: datetime | None = None
    ) -> list[CronTrigger]:
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
        self, trigger_id: UUID, hours: int = 24, limit: int = 100
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
        self, trigger_id: UUID, start_time: datetime, end_time: datetime
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

    async def execute_trigger(
        self, trigger_id: UUID, trigger_data: dict[str, Any]
    ) -> TriggerExecution:
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
                trigger_id, "Trigger is inactive", trigger_data
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
                        trigger_id, "Trigger conditions not met", trigger_data
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
                    task_parameters=task_params,
                )

                task_id = task.id
                logger.info(f"Created task {task_id} from trigger {trigger_id}")
            else:
                logger.warning(
                    f"Task service not available, skipping task creation for trigger {trigger_id}"
                )

            # Calculate execution time
            execution_time_ms = int((time.time() - start_time) * 1000)

            # Record successful execution
            execution = await self._record_execution_success(
                trigger_id, execution_time_ms, task_id, trigger_data
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
                trigger_id, str(e), trigger_data, execution_time_ms
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
        task_id: UUID | None = None,
        trigger_data: dict[str, Any] | None = None,
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
            trigger_data=trigger_data or {},
        )

    async def _record_execution_failure(
        self,
        trigger_id: UUID,
        error_message: str,
        trigger_data: dict[str, Any] | None = None,
        execution_time_ms: int = 0,
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
            trigger_data=trigger_data or {},
        )

    async def _build_task_parameters(
        self, trigger: Trigger, trigger_data: dict[str, Any]
    ) -> dict[str, Any]:
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
        params.update(
            {
                "trigger_id": str(trigger.id),
                "trigger_type": trigger.trigger_type.value,
                "trigger_name": trigger.name,
                "execution_time": datetime.utcnow().isoformat(),
            }
        )

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
                    trigger_context=trigger_context,
                )

                # Merge LLM-extracted parameters (don't override existing ones)
                for key, value in llm_params.items():
                    if key not in params:
                        params[key] = value

                logger.info(
                    f"Enhanced task parameters with LLM extraction for trigger {trigger.id}"
                )

            except Exception as e:
                logger.warning(f"LLM parameter extraction failed for trigger {trigger.id}: {e}")
                # Continue with basic parameters

        return params

    async def evaluate_trigger_conditions(
        self, trigger: Trigger, event_data: dict[str, Any]
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
                    trigger_context=trigger_context,
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

    def _get_nested_value(self, data: dict[str, Any], field_path: str) -> Any:
        """Get nested value from dictionary using dot notation.

        Args:
            data: Dictionary to search in
            field_path: Dot-separated path (e.g., "request.body.message_type")

        Returns:
            The value at the path, or None if not found
        """
        try:
            value = data
            for key in field_path.split("."):
                if isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    return None
            return value
        except Exception:
            return None

    async def _evaluate_simple_conditions(
        self, conditions: dict[str, Any], event_data: dict[str, Any]
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
                        return False

            return True

        except Exception as e:
            logger.error(f"Error in simple condition evaluation: {e}")
            return True  # Default to True on evaluation errors

    async def extract_task_parameters_with_llm(
        self, instruction: str, event_data: dict[str, Any], trigger_context: dict[str, Any]
    ) -> dict[str, Any]:
        """Extract task parameters using LLM.

        Args:
            instruction: LLM instruction for parameter extraction
            event_data: Event data to extract from
            trigger_context: Trigger context information

        Returns:
            Dictionary of extracted parameters
        """
        if not self.llm_condition_evaluator:
            return {}

        try:
            return await self.llm_condition_evaluator.extract_parameters(
                instruction=instruction, event_data=event_data, trigger_context=trigger_context
            )
        except Exception as e:
            logger.error(f"LLM parameter extraction failed: {e}")
            return {}

    # Enhanced monitoring and execution history methods for task 14

    async def get_execution_history_paginated(
        self,
        trigger_id: UUID,
        status: ExecutionStatus | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[TriggerExecution], int]:
        """Get paginated execution history with filtering.

        Args:
            trigger_id: The trigger ID
            status: Optional status filter
            start_time: Optional start time filter
            end_time: Optional end time filter
            limit: Maximum number of executions to return
            offset: Number of executions to skip

        Returns:
            Tuple of (executions list, total count)
        """
        # Get filtered executions
        executions = await self.trigger_execution_repository.list_executions_paginated(
            trigger_id=trigger_id,
            status=status,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
        )

        # Get total count with same filters
        total = await self.trigger_execution_repository.count_executions_filtered(
            trigger_id=trigger_id, status=status, start_time=start_time, end_time=end_time
        )

        return executions, total

    async def get_execution_metrics(self, trigger_id: UUID, hours: int = 24) -> dict[str, Any]:
        """Get execution metrics for a trigger.

        Args:
            trigger_id: The trigger ID
            hours: Time period in hours

        Returns:
            Dictionary with execution metrics
        """
        return await self.trigger_execution_repository.get_execution_metrics(trigger_id, hours)

    async def get_execution_timeline(
        self, trigger_id: UUID, hours: int = 24, bucket_size_minutes: int = 60
    ) -> list[dict[str, Any]]:
        """Get execution timeline with bucketed counts.

        Args:
            trigger_id: The trigger ID
            hours: Time period in hours
            bucket_size_minutes: Size of time buckets in minutes

        Returns:
            List of timeline data points
        """
        return await self.trigger_execution_repository.get_execution_timeline(
            trigger_id, hours, bucket_size_minutes
        )

    async def get_execution_correlations(
        self, trigger_id: UUID, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        """Get execution correlation data with task tracking.

        Args:
            trigger_id: The trigger ID
            limit: Maximum number of executions to return
            offset: Number of executions to skip

        Returns:
            Tuple of (correlation data list, total count)
        """
        # Get executions with correlation info
        correlations = await self.trigger_execution_repository.get_executions_with_task_correlation(
            trigger_id, limit, offset
        )

        # Get total count for pagination
        total = await self.trigger_execution_repository.count_executions_filtered(
            trigger_id=trigger_id
        )

        return correlations, total
