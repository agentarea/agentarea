"""Trigger execution activities for Temporal workflows.

These activities handle the actual execution of triggers, condition evaluation,
and task creation when triggers fire.
"""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_common.config import get_database
from temporalio import activity

from ..interfaces import ActivityDependencies

logger = logging.getLogger(__name__)


def make_trigger_activities(dependencies: ActivityDependencies):
    """Create trigger activity functions with injected dependencies.
    
    Args:
        dependencies: Basic dependencies needed to create services within activities
        
    Returns:
        List of activity functions ready for worker registration
    """

    @activity.defn(name="execute_trigger_activity")
    async def execute_trigger_activity(trigger_id: UUID, execution_data: dict[str, Any]) -> dict[str, Any]:
        """Execute a trigger and create a task if conditions are met.
        
        Args:
            trigger_id: The ID of the trigger to execute
            execution_data: Additional data about the execution
            
        Returns:
            Dictionary containing execution result and metadata
            
        Raises:
            TriggerNotFoundError: If trigger doesn't exist
            TriggerValidationError: If trigger configuration is invalid
        """
        start_time = datetime.utcnow()

        try:
            from agentarea_triggers.domain.enums import ExecutionStatus
            from agentarea_triggers.infrastructure.repository import TriggerExecutionRepository, TriggerRepository
            from agentarea_triggers.trigger_service import TriggerNotFoundError, TriggerService, TriggerValidationError

            database = get_database()
            async with database.async_session_factory() as session:
                trigger_repository = TriggerRepository(session)
                trigger_execution_repository = TriggerExecutionRepository(session)

                trigger_service = TriggerService(
                    trigger_repository=trigger_repository,
                    trigger_execution_repository=trigger_execution_repository,
                    event_broker=dependencies.event_broker,
                    agent_repository=None,
                    task_service=None,
                    llm_service=None
                )

                trigger = await trigger_service.get_trigger(trigger_id)
                if not trigger:
                    raise TriggerNotFoundError(f"Trigger {trigger_id} not found")

                if not trigger.is_active:
                    logger.info(f"Trigger {trigger_id} is inactive, skipping execution")
                    return {
                        "trigger_id": str(trigger_id),
                        "status": "skipped",
                        "reason": "trigger_inactive",
                        "execution_time_ms": 0
                    }

                if trigger.is_rate_limited():
                    logger.info(f"Trigger {trigger_id} is rate limited, skipping execution")
                    return {
                        "trigger_id": str(trigger_id),
                        "status": "skipped",
                        "reason": "rate_limited",
                        "execution_time_ms": 0
                    }

                conditions_met = True

                # Evaluate trigger conditions
                conditions_met = True
                if trigger.conditions:
                    try:
                        # Use LLM service for condition evaluation if available
                        if trigger_service.llm_service:
                            # TODO: Implement LLM-based condition evaluation
                            # For now, assume conditions are met
                            conditions_met = True
                        else:
                            # Simple rule-based condition evaluation
                            conditions_met = await trigger_service.evaluate_trigger_conditions(trigger, execution_data)
                    except Exception as condition_error:
                        logger.warning(f"Error evaluating conditions for trigger {trigger_id}: {condition_error}")
                        # Default to conditions met to avoid blocking execution
                        conditions_met = True

                if not conditions_met:
                    logger.info(f"Trigger {trigger_id} conditions not met, skipping execution")
                    return {
                        "trigger_id": str(trigger_id),
                        "status": "skipped",
                        "reason": "conditions_not_met",
                        "execution_time_ms": int((datetime.utcnow() - start_time).total_seconds() * 1000)
                    }

                # Create task from trigger
                task_id = None
                try:
                    # Import TaskService and create task
                    from agentarea_tasks.task_service import TaskService
                    from agentarea_tasks.infrastructure.repository import TaskRepository

                    # Create task repository and service
                    task_repository = TaskRepository(session)
                    task_service = TaskService(
                        task_repository=task_repository,
                        event_broker=dependencies.event_broker,
                        task_manager=None,  # Not needed for task creation
                        agent_repository=None,
                        workflow_service=None
                    )

                    # Build task parameters
                    task_params = await trigger_service._build_task_parameters(trigger, execution_data)

                    # Create task
                    task = await task_service.create_task_from_params(
                        title=f"Trigger: {trigger.name}",
                        description=trigger.description or f"Execution of trigger {trigger.name}",
                        query=trigger.description or f"Execute trigger {trigger.name}",
                        user_id=trigger.created_by,
                        agent_id=trigger.agent_id,
                        task_parameters=task_params
                    )

                    task_id = task.id
                    logger.info(f"Created task {task_id} from trigger {trigger_id}")
                        
                except Exception as task_error:
                    logger.error(f"Failed to create task for trigger {trigger_id}: {task_error}")
                    # Don't fail the entire trigger execution if task creation fails
                    # Record the error but continue with execution recording

                execution_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

                execution_result = await trigger_service.record_execution(
                    trigger_id=trigger_id,
                    status=ExecutionStatus.SUCCESS,
                    execution_time_ms=execution_time_ms,
                    task_id=task_id,
                    trigger_data=execution_data
                )

                logger.info(f"Trigger {trigger_id} executed successfully, task_id: {task_id}")

                return {
                    "trigger_id": str(trigger_id),
                    "status": "success",
                    "task_id": str(task_id) if task_id else None,
                    "execution_id": str(execution_result.id),
                    "execution_time_ms": execution_time_ms,
                    "trigger_data": execution_data
                }

        except Exception as e:
            from agentarea_triggers.domain.enums import ExecutionStatus
            from agentarea_triggers.infrastructure.repository import TriggerExecutionRepository, TriggerRepository
            from agentarea_triggers.trigger_service import TriggerNotFoundError, TriggerService, TriggerValidationError

            if isinstance(e, (TriggerNotFoundError, TriggerValidationError)):
                raise

            execution_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            logger.error(f"Error executing trigger {trigger_id}: {e}")

            try:
                database = get_database()
                async with database.async_session_factory() as session:
                    trigger_repository = TriggerRepository(session)
                    trigger_execution_repository = TriggerExecutionRepository(session)

                    trigger_service = TriggerService(
                        trigger_repository=trigger_repository,
                        trigger_execution_repository=trigger_execution_repository,
                        event_broker=dependencies.event_broker,
                        agent_repository=None,
                        task_service=None,
                        llm_service=None
                    )

                    await trigger_service.record_execution(
                        trigger_id=trigger_id,
                        status=ExecutionStatus.FAILED,
                        execution_time_ms=execution_time_ms,
                        error_message=str(e),
                        trigger_data=execution_data
                    )
            except Exception as record_error:
                logger.error(f"Failed to record execution failure for trigger {trigger_id}: {record_error}")

            raise

    @activity.defn(name="record_trigger_execution_activity")
    async def record_trigger_execution_activity(
        trigger_id: UUID,
        execution_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Record a trigger execution result.
        
        Args:
            trigger_id: The ID of the trigger
            execution_data: Execution result data
            
        Returns:
            Dictionary containing the recorded execution info
        """
        try:
            from agentarea_triggers.domain.enums import ExecutionStatus
            from agentarea_triggers.infrastructure.repository import TriggerExecutionRepository, TriggerRepository
            from agentarea_triggers.trigger_service import TriggerService

            database = get_database()
            async with database.async_session_factory() as session:
                trigger_repository = TriggerRepository(session)
                trigger_execution_repository = TriggerExecutionRepository(session)

                trigger_service = TriggerService(
                    trigger_repository=trigger_repository,
                    trigger_execution_repository=trigger_execution_repository,
                    event_broker=dependencies.event_broker,
                    agent_repository=None,
                    task_service=None,
                    llm_service=None
                )

                status = ExecutionStatus(execution_data["status"])
                execution_time_ms = execution_data.get("execution_time_ms", 0)
                error_message = execution_data.get("error_message")
                task_id = execution_data.get("task_id")
                trigger_data = execution_data.get("trigger_data", {})

                execution_result = await trigger_service.record_execution(
                    trigger_id=trigger_id,
                    status=status,
                    execution_time_ms=execution_time_ms,
                    task_id=UUID(task_id) if task_id else None,
                    error_message=error_message,
                    trigger_data=trigger_data
                )

                logger.info(f"Recorded execution for trigger {trigger_id}: {status}")

                return {
                    "execution_id": str(execution_result.id),
                    "trigger_id": str(trigger_id),
                    "status": status.value,
                    "recorded_at": execution_result.executed_at.isoformat()
                }

        except Exception as e:
            logger.error(f"Failed to record execution for trigger {trigger_id}: {e}")
            raise

    @activity.defn(name="evaluate_trigger_conditions_activity")
    async def evaluate_trigger_conditions_activity(
        trigger_id: UUID,
        event_data: dict[str, Any]
    ) -> bool:
        """Evaluate trigger conditions using LLM service.
        
        Args:
            trigger_id: The ID of the trigger
            event_data: Event data to evaluate against
            
        Returns:
            True if conditions are met, False otherwise
        """
        try:
            from agentarea_triggers.infrastructure.repository import TriggerExecutionRepository, TriggerRepository
            from agentarea_triggers.trigger_service import TriggerService

            database = get_database()
            async with database.async_session_factory() as session:
                trigger_repository = TriggerRepository(session)
                trigger_execution_repository = TriggerExecutionRepository(session)

                trigger_service = TriggerService(
                    trigger_repository=trigger_repository,
                    trigger_execution_repository=trigger_execution_repository,
                    event_broker=dependencies.event_broker,
                    agent_repository=None,
                    task_service=None,
                    llm_service=None
                )

                trigger = await trigger_service.get_trigger(trigger_id)
                if not trigger:
                    logger.warning(f"Trigger {trigger_id} not found for condition evaluation")
                    return False

                # Use the trigger service's condition evaluation method
                return await trigger_service.evaluate_trigger_conditions(trigger, event_data)

        except Exception as e:
            logger.error(f"Error evaluating conditions for trigger {trigger_id}: {e}")
            return False

    @activity.defn(name="create_task_from_trigger_activity")
    async def create_task_from_trigger_activity(
        trigger_id: UUID,
        execution_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a task from a trigger execution.
        
        Args:
            trigger_id: The ID of the trigger
            execution_data: Execution data to include in task parameters
            
        Returns:
            Dictionary containing task creation result
        """
        try:
            from agentarea_triggers.infrastructure.repository import TriggerExecutionRepository, TriggerRepository
            from agentarea_triggers.trigger_service import TriggerService
            from agentarea_tasks.task_service import TaskService
            from agentarea_tasks.infrastructure.repository import TaskRepository

            database = get_database()
            async with database.async_session_factory() as session:
                # Create repositories
                trigger_repository = TriggerRepository(session)
                trigger_execution_repository = TriggerExecutionRepository(session)
                task_repository = TaskRepository(session)

                # Create services
                trigger_service = TriggerService(
                    trigger_repository=trigger_repository,
                    trigger_execution_repository=trigger_execution_repository,
                    event_broker=dependencies.event_broker,
                    agent_repository=None,
                    task_service=None,
                    llm_service=None
                )

                # Get the trigger
                trigger = await trigger_service.get_trigger(trigger_id)
                if not trigger:
                    raise ValueError(f"Trigger {trigger_id} not found")

                # Create task service with minimal dependencies for task creation
                task_service = TaskService(
                    task_repository=task_repository,
                    event_broker=dependencies.event_broker,
                    task_manager=None,  # Not needed for task creation
                    agent_repository=None,
                    workflow_service=None
                )

                # Build task parameters
                task_params = await trigger_service._build_task_parameters(trigger, execution_data)

                # Create task
                task = await task_service.create_task_from_params(
                    title=f"Trigger: {trigger.name}",
                    description=trigger.description or f"Execution of trigger {trigger.name}",
                    query=trigger.description or f"Execute trigger {trigger.name}",
                    user_id=trigger.created_by,
                    agent_id=trigger.agent_id,
                    task_parameters=task_params
                )

                logger.info(f"Created task {task.id} from trigger {trigger_id}")

                return {
                    "task_id": str(task.id),
                    "trigger_id": str(trigger_id),
                    "status": "created",
                    "task_parameters": task_params
                }

        except Exception as e:
            logger.error(f"Failed to create task from trigger {trigger_id}: {e}")
            return {
                "task_id": None,
                "trigger_id": str(trigger_id),
                "status": "failed",
                "error": str(e)
            }

    return [
        execute_trigger_activity,
        record_trigger_execution_activity,
        evaluate_trigger_conditions_activity,
        create_task_from_trigger_activity,
    ]
