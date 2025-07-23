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
    from uuid import UUID
    from datetime import datetime


class TriggerActivities:
    """Activity function references to avoid hardcoded strings."""

    execute_trigger = "execute_trigger_activity"
    record_trigger_execution = "record_trigger_execution_activity"
    evaluate_trigger_conditions = "evaluate_trigger_conditions_activity"
    create_task_from_trigger = "create_task_from_trigger_activity"


@workflow.defn
class TriggerExecutionWorkflow:
    """Workflow for executing a single trigger instance.
    
    This workflow is started by Temporal Schedules when cron triggers fire.
    It executes the trigger and records the execution result.
    """

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
        
        try:
            # Step 1: Evaluate trigger conditions
            conditions_met = await workflow.execute_activity(
                TriggerActivities.evaluate_trigger_conditions,
                trigger_id,
                execution_data,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=2)
            )
            
            if not conditions_met:
                workflow.logger.info(f"Trigger {trigger_id} conditions not met, skipping execution")
                return {
                    "trigger_id": str(trigger_id),
                    "status": "skipped",
                    "reason": "conditions_not_met",
                    "execution_time_ms": 0
                }
            
            # Step 2: Execute the trigger with retry policy
            execution_result = await workflow.execute_activity(
                TriggerActivities.execute_trigger,
                trigger_id,
                execution_data,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(minutes=1),
                    maximum_attempts=3,
                    non_retryable_error_types=["TriggerValidationError", "TriggerNotFoundError"]
                )
            )
            
            workflow.logger.info(f"Trigger {trigger_id} executed successfully")
            return execution_result
            
        except ApplicationError as e:
            workflow.logger.error(f"Trigger {trigger_id} execution failed: {e}")
            
            # Record the failure
            await workflow.execute_activity(
                TriggerActivities.record_trigger_execution,
                trigger_id,
                {
                    "status": "failed",
                    "error_message": str(e),
                    "execution_time_ms": 0,
                    "executed_at": execution_data.get("execution_time", datetime.utcnow().isoformat())
                },
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=2)
            )
            
            # Re-raise the error to mark workflow as failed
            raise
        
        except Exception as e:
            workflow.logger.error(f"Unexpected error in trigger {trigger_id} execution: {e}")
            
            # Record the unexpected failure
            await workflow.execute_activity(
                TriggerActivities.record_trigger_execution, 
                trigger_id,
                {
                    "status": "failed",
                    "error_message": f"Unexpected error: {str(e)}",
                    "execution_time_ms": 0,
                    "executed_at": execution_data.get("execution_time", datetime.utcnow().isoformat())
                },
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=2)
            )
            
            # Convert to ApplicationError for proper workflow failure handling
            raise ApplicationError(f"Unexpected trigger execution error: {str(e)}")