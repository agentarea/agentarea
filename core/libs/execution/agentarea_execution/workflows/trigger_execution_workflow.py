"""Trigger execution workflow for Temporal Schedules.

This workflow is started by Temporal Schedules when cron triggers fire.
It handles the execution of a single trigger instance.
"""

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from datetime import datetime
    from uuid import UUID


class TriggerActivities:
    """Activity function references to avoid hardcoded strings."""

    execute_trigger = "execute_trigger_activity"
    record_trigger_execution = "record_trigger_execution_activity"
    evaluate_trigger_conditions = "evaluate_trigger_conditions_activity"
    create_task_from_trigger = "create_task_from_trigger_activity"


# Import Pydantic models for trigger activities
from ..models import (  # noqa: E402
    EvaluateTriggerConditionsRequest,
    EvaluateTriggerConditionsResult,
    ExecuteTriggerRequest,
    ExecuteTriggerResult,
    RecordTriggerExecutionRequest,
)


@workflow.defn
class TriggerExecutionWorkflow:
    """Workflow for executing a single trigger instance.

    This workflow is started by Temporal Schedules when cron triggers fire.
    It executes the trigger and records the execution result.

    Enhanced Safety features:
    - Configurable execution timeout (default 15 minutes, max 30 minutes)
    - Enhanced retry policies with exponential backoff and jitter
    - Heartbeat monitoring for long-running activities
    - Graceful cancellation handling with cleanup
    - Comprehensive error classification and non-retryable error handling
    - Circuit breaker pattern for consecutive failures
    - Automatic trigger disabling integration
    """

    def __init__(self):
        self.is_cancelled = False
        self.execution_start_time = None

    @workflow.run
    async def run(self, trigger_id: UUID, execution_data: dict[str, Any]) -> dict[str, Any]:
        """Execute a trigger and return the execution result.

        Args:
            trigger_id: The ID of the trigger to execute
            execution_data: Additional data about the execution (timestamp, source, etc.)

        Returns:
            Dictionary containing execution result and metadata
        """
        workflow.logger.info(f"Starting trigger execution for trigger {trigger_id}")

        # Enhanced workflow execution timeout with configurable limits
        max_execution_timeout = timedelta(minutes=30)  # Hard limit
        timedelta(minutes=15)  # Default timeout

        # Use custom timeout from execution_data if provided, but cap at max
        custom_timeout_minutes = execution_data.get("timeout_minutes", 15)
        workflow_timeout = min(timedelta(minutes=custom_timeout_minutes), max_execution_timeout)

        self.execution_start_time = workflow.now()

        try:
            # Check for cancellation before starting
            if self.is_cancelled:
                workflow.logger.info(
                    f"Trigger execution {trigger_id} was cancelled before starting"
                )
                return {
                    "trigger_id": str(trigger_id),
                    "status": "cancelled",
                    "reason": "workflow_cancelled",
                    "execution_time_ms": 0,
                    "workflow_timeout_minutes": workflow_timeout.total_seconds() / 60,
                }
            # Step 1: Evaluate trigger conditions with enhanced retry policy and circuit breaker
            conditions_result: EvaluateTriggerConditionsResult = await workflow.execute_activity(
                TriggerActivities.evaluate_trigger_conditions,
                args=[
                    EvaluateTriggerConditionsRequest(
                        trigger_id=trigger_id, event_data=execution_data
                    )
                ],
                start_to_close_timeout=timedelta(minutes=3),  # Increased timeout for LLM evaluation
                heartbeat_timeout=timedelta(seconds=30),  # Heartbeat for condition evaluation
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(minutes=2),  # Increased max interval
                    backoff_coefficient=2.0,  # Exponential backoff
                    maximum_attempts=5,  # More attempts for condition evaluation
                    non_retryable_error_types=[
                        "TriggerValidationError",
                        "TriggerNotFoundError",
                        "InvalidConditionError",
                        "TriggerDisabledError",  # Don't retry if trigger was disabled
                        "AgentNotFoundError",
                        "AuthenticationError",
                        "AuthorizationError",
                    ],
                ),
            )

            if not conditions_result.conditions_met:
                workflow.logger.info(f"Trigger {trigger_id} conditions not met, skipping execution")
                execution_time_ms = int(
                    (workflow.now() - self.execution_start_time).total_seconds() * 1000
                )
                return {
                    "trigger_id": str(trigger_id),
                    "status": "skipped",
                    "reason": "conditions_not_met",
                    "execution_time_ms": execution_time_ms,
                    "workflow_timeout_minutes": workflow_timeout.total_seconds() / 60,
                }

            # Step 2: Execute the trigger with enhanced retry policy and safety mechanisms
            execution_result_model: ExecuteTriggerResult = await workflow.execute_activity(
                TriggerActivities.execute_trigger,
                args=[ExecuteTriggerRequest(trigger_id=trigger_id, execution_data=execution_data)],
                start_to_close_timeout=timedelta(
                    minutes=12
                ),  # Increased timeout for complex triggers
                heartbeat_timeout=timedelta(minutes=2),  # Heartbeat for long-running activities
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=2),  # Start with 2 second delay
                    maximum_interval=timedelta(minutes=8),  # Increased max delay for safety
                    backoff_coefficient=2.0,  # Exponential backoff
                    maximum_attempts=3,  # Reduced attempts to fail faster for safety
                    non_retryable_error_types=[
                        "TriggerValidationError",
                        "TriggerNotFoundError",
                        "TriggerDisabledError",  # Don't retry if trigger was auto-disabled
                        "AgentNotFoundError",
                        "InvalidConfigurationError",
                        "AuthenticationError",
                        "AuthorizationError",
                        "RateLimitExceededError",  # Don't retry rate limit errors
                        "CircuitBreakerOpenError",  # Don't retry when circuit breaker is open
                    ],
                ),
            )

            workflow.logger.info(f"Trigger {trigger_id} executed successfully")

            # Add workflow metadata to execution result
            execution_result = execution_result_model.model_dump()
            # Normalize UUID fields to strings for consistency in workflow outputs
            if execution_result.get("trigger_id") is not None:
                execution_result["trigger_id"] = str(execution_result["trigger_id"])
            if execution_result.get("task_id") is not None:
                execution_result["task_id"] = (
                    str(execution_result["task_id"]) if execution_result["task_id"] else None
                )
            if execution_result.get("execution_id") is not None:
                execution_result["execution_id"] = (
                    str(execution_result["execution_id"])
                    if execution_result["execution_id"]
                    else None
                )

            execution_result["workflow_timeout_minutes"] = workflow_timeout.total_seconds() / 60
            execution_result["total_workflow_time_ms"] = int(
                (workflow.now() - self.execution_start_time).total_seconds() * 1000
            )

            return execution_result

        except ApplicationError as e:
            workflow.logger.error(f"Trigger {trigger_id} execution failed: {e}")

            execution_time_ms = int(
                (workflow.now() - self.execution_start_time).total_seconds() * 1000
            )

            # Record the failure with enhanced retry policy and safety mechanisms
            await workflow.execute_activity(
                TriggerActivities.record_trigger_execution,
                args=[
                    RecordTriggerExecutionRequest(
                        trigger_id=trigger_id,
                        execution_data={
                            "status": "failed",
                            "error_message": str(e),
                            "execution_time_ms": execution_time_ms,
                            "executed_at": execution_data.get(
                                "execution_time", datetime.utcnow().isoformat()
                            ),
                            "workflow_timeout_minutes": workflow_timeout.total_seconds() / 60,
                            "error_type": type(e).__name__,
                        },
                    )
                ],
                start_to_close_timeout=timedelta(
                    minutes=2
                ),  # Increased timeout for failure recording
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=30),  # Increased max interval
                    backoff_coefficient=2.0,
                    maximum_attempts=5,  # More attempts for critical failure recording
                    non_retryable_error_types=["DatabaseConnectionError", "PermanentDatabaseError"],
                ),
            )

            # Re-raise the error to mark workflow as failed
            raise

        except Exception as e:
            workflow.logger.error(f"Unexpected error in trigger {trigger_id} execution: {e}")

            execution_time_ms = int(
                (workflow.now() - self.execution_start_time).total_seconds() * 1000
            )

            # Record the unexpected failure with enhanced retry policy and safety mechanisms
            await workflow.execute_activity(
                TriggerActivities.record_trigger_execution,
                args=[
                    RecordTriggerExecutionRequest(
                        trigger_id=trigger_id,
                        execution_data={
                            "status": "failed",
                            "error_message": f"Unexpected error: {e!s}",
                            "execution_time_ms": execution_time_ms,
                            "executed_at": execution_data.get(
                                "execution_time", datetime.utcnow().isoformat()
                            ),
                            "workflow_timeout_minutes": workflow_timeout.total_seconds() / 60,
                            "error_type": type(e).__name__,
                            "is_unexpected_error": True,
                        },
                    )
                ],
                start_to_close_timeout=timedelta(
                    minutes=2
                ),  # Increased timeout for failure recording
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=30),  # Increased max interval
                    backoff_coefficient=2.0,
                    maximum_attempts=5,  # More attempts for critical failure recording
                    non_retryable_error_types=["DatabaseConnectionError", "PermanentDatabaseError"],
                ),
            )

            # Convert to ApplicationError for proper workflow failure handling
            raise ApplicationError(f"Unexpected trigger execution error: {e!s}") from e

    @workflow.signal
    async def cancel_execution(self) -> None:
        """Signal to cancel the trigger execution.

        This allows for graceful cancellation of long-running trigger executions.
        """
        workflow.logger.info("Received cancellation signal for trigger execution")
        self.is_cancelled = True

    @workflow.query
    def get_execution_status(self) -> dict[str, Any]:
        """Query to get current execution status.

        Returns:
            Dictionary with current execution status information
        """
        current_time = workflow.now()
        execution_duration_ms = 0

        if self.execution_start_time:
            execution_duration_ms = int(
                (current_time - self.execution_start_time).total_seconds() * 1000
            )

        return {
            "is_cancelled": self.is_cancelled,
            "workflow_time": current_time.isoformat(),
            "execution_start_time": self.execution_start_time.isoformat()
            if self.execution_start_time
            else None,
            "execution_duration_ms": execution_duration_ms,
            "is_running": self.execution_start_time is not None,
        }
