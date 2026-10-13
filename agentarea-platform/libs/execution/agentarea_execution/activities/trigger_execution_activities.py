"""Trigger execution activities for Temporal workflows.

These activities handle the actual execution of triggers, condition evaluation,
and task creation when triggers fire.
"""

from datetime import datetime
from uuid import UUID, uuid5

from agentarea_common.config import get_database
from agentarea_triggers.logging_utils import (
    DependencyUnavailableError,
    TriggerExecutionError,
    TriggerLogger,
    set_correlation_id,
)
from temporalio import activity

from ..interfaces import ActivityDependencies
from ..models import (
    EvaluateTriggerConditionsRequest,
    EvaluateTriggerConditionsResult,
    ExecuteTriggerRequest,
    ExecuteTriggerResult,
    RecordTriggerExecutionRequest,
    RecordTriggerExecutionResult,
    TriggerOutcome,
    TriggerSkipReason,
)

logger = TriggerLogger(__name__)

_SCHEDULED_TASK_NAMESPACE = UUID("6f1d4c2a-8e3b-4a57-9c0d-2b7e5f9a1c83")


def scheduled_task_id(workflow_id: str) -> UUID:
    """The task a schedule firing starts; every attempt of that firing names the same one."""
    return uuid5(_SCHEDULED_TASK_NAMESPACE, workflow_id)


async def _resolve_trigger_context(session, trigger_id: UUID):
    """Resolve UserContext from trigger ORM for workspace-scoped repositories.

    The trigger is found across workspaces, since its id is all the activity
    has; the rest of the activity is then confined to the trigger's workspace.

    Raises:
        ValueError: If trigger not found — prevents silent fallback to system context.
    """
    from agentarea_common.auth.context import UserContext
    from agentarea_common.base.tenant_scope import bind_workspace_scope, unscoped
    from agentarea_triggers.infrastructure.orm import TriggerORM

    with unscoped("a trigger activity is handed a trigger id; the trigger names the workspace"):
        trigger_orm = await session.get(TriggerORM, trigger_id)
    if not trigger_orm:
        raise ValueError(f"Trigger {trigger_id} not found — cannot resolve workspace context")

    bind_workspace_scope(trigger_orm.workspace_id)
    return UserContext(
        user_id=trigger_orm.created_by,
        workspace_id=trigger_orm.workspace_id,
    )


def make_trigger_activities(dependencies: ActivityDependencies):
    """Create trigger activity functions with injected dependencies.

    Args:
        dependencies: Basic dependencies needed to create services within activities

    Returns:
        List of activity functions ready for worker registration
    """

    def _condition_evaluator(session, user_context):
        from agentarea_triggers.llm_condition_evaluator import build_condition_evaluator

        return build_condition_evaluator(
            session=session,
            user_context=user_context,
            secret_manager=dependencies.secret_manager_factory.create(
                session=session, user_context=user_context
            ),
            secret_manager_factory=dependencies.secret_manager_factory,
            event_broker=dependencies.event_broker,
        )

    def _trigger_service(session, user_context, *, evaluate_conditions=False, task_service=None):
        """A TriggerService that can pause the schedule of a trigger it disables."""
        from agentarea_common.base.repository_factory import RepositoryFactory
        from agentarea_triggers.temporal_schedule_manager import TemporalScheduleManager
        from agentarea_triggers.trigger_service import TriggerService

        return TriggerService(
            repository_factory=RepositoryFactory(session, user_context),
            event_broker=dependencies.event_broker,
            task_service=task_service,
            llm_condition_evaluator=(
                _condition_evaluator(session, user_context) if evaluate_conditions else None
            ),
            temporal_schedule_manager=TemporalScheduleManager(
                activity.client(), task_queue=dependencies.settings.triggers.QUEUE
            ),
        )

    def _task_service(session, user_context):
        from agentarea_common.base.repository_factory import RepositoryFactory
        from agentarea_tasks.infrastructure.repository import TaskRepository
        from agentarea_tasks.task_service import TaskService
        from agentarea_tasks.temporal_task_manager import TemporalTaskManager

        repository_factory = RepositoryFactory(session, user_context)
        return TaskService(
            repository_factory=repository_factory,
            event_broker=dependencies.event_broker,
            task_manager=TemporalTaskManager(
                task_repository=repository_factory.create_repository(TaskRepository),
                temporal_executor=dependencies.workflow_executor,
            ),
        )

    @activity.defn(name="execute_trigger_activity")
    async def execute_trigger_activity(request: ExecuteTriggerRequest) -> ExecuteTriggerResult:
        """Execute a trigger and create a task if conditions are met.

        Args:
            request: ExecuteTriggerRequest containing trigger_id and execution_data

        Returns:
            ExecuteTriggerResult containing execution result and metadata

        Raises:
            TriggerExecutionError: If trigger execution fails
        """
        trigger_id = request.trigger_id
        execution_data = request.execution_data

        # The firing's workflow id is the same on every attempt of it, so it
        # names the task and ties the run back to the schedule tick.
        correlation_id = activity.info().workflow_id
        if correlation_id is None:
            raise TriggerExecutionError(
                "execute_trigger_activity runs only inside a trigger workflow",
                trigger_id=str(trigger_id),
            )
        set_correlation_id(correlation_id)
        start_time = datetime.utcnow()

        try:
            logger.info(
                "Starting trigger execution",
                trigger_id=trigger_id,
                execution_source=execution_data.get("source", "unknown"),
            )

            from agentarea_tasks.domain.models import TaskProvenance
            from agentarea_triggers.logging_utils import TriggerNotFoundError

            database = get_database()
            if not database:
                error_msg = "Database connection not available"
                logger.error(error_msg, trigger_id=trigger_id)
                raise DependencyUnavailableError(
                    error_msg, dependency="database", trigger_id=str(trigger_id)
                )

            async with database.async_session_factory() as session:
                user_context = await _resolve_trigger_context(session, trigger_id)
                trigger_service = _trigger_service(
                    session,
                    user_context,
                    evaluate_conditions=True,
                    task_service=_task_service(session, user_context),
                )

                # Get trigger with error handling
                try:
                    trigger = await trigger_service.get_trigger(trigger_id)
                    if not trigger:
                        error_msg = f"Trigger {trigger_id} not found"
                        logger.error(error_msg, trigger_id=trigger_id)
                        raise TriggerNotFoundError(error_msg, trigger_id=str(trigger_id))
                except Exception as e:
                    if isinstance(e, TriggerNotFoundError):
                        raise
                    error_msg = f"Error retrieving trigger: {e}"
                    logger.error(error_msg, trigger_id=trigger_id, exc_info=True)
                    raise TriggerExecutionError(
                        error_msg, trigger_id=str(trigger_id), original_error=str(e)
                    ) from None

                # Checked before the extractor runs, so a switched-off poller
                # does not consume what it would have fetched.
                if not trigger.is_active:
                    logger.info(
                        "Trigger is inactive, skipping execution",
                        trigger_id=trigger_id,
                        trigger_name=trigger.name,
                    )
                    return ExecuteTriggerResult(
                        trigger_id=trigger_id,
                        status=TriggerOutcome.SKIPPED,
                        reason=TriggerSkipReason.TRIGGER_INACTIVE,
                        execution_time_ms=0,
                        trigger_data=execution_data,
                    )

                # Run data extractor if configured (poll-based channels like email)
                data_extractor = getattr(trigger, "data_extractor", None)
                if data_extractor:
                    try:
                        from agentarea_triggers.extractors import get_extractor

                        extractor_cls = get_extractor(data_extractor)
                        if extractor_cls:
                            extractor = extractor_cls()
                            # The id travels with the config because an extractor
                            # resolves its credentials from the secret store per
                            # trigger; passwords never live in the config column.
                            extractor_config = {
                                **(getattr(trigger, "data_extractor_config", None) or {}),
                                "trigger_id": str(trigger_id),
                            }
                            extraction_result = await extractor.extract(
                                extractor_config,
                                getattr(trigger, "data_extractor_state", None),
                            )

                            if not extraction_result.has_new_data:
                                logger.info(
                                    "Data extractor found no new data, skipping",
                                    trigger_id=trigger_id,
                                    extractor=data_extractor,
                                )
                                return ExecuteTriggerResult(
                                    trigger_id=trigger_id,
                                    status=TriggerOutcome.SKIPPED,
                                    reason=TriggerSkipReason.NO_NEW_DATA,
                                    execution_time_ms=int(
                                        (datetime.utcnow() - start_time).total_seconds() * 1000
                                    ),
                                    trigger_data=execution_data,
                                )

                            # Enrich execution_data with extracted content
                            execution_data["extracted_events"] = extraction_result.events
                            if extraction_result.channel_origin:
                                execution_data["channel_origin"] = extraction_result.channel_origin

                            # Persist updated extractor state
                            await trigger_service.trigger_repository.update_extractor_state(
                                trigger_id, extraction_result.updated_state
                            )
                            await session.commit()

                            logger.info(
                                f"Data extractor found {len(extraction_result.events)} new events",
                                trigger_id=trigger_id,
                                extractor=data_extractor,
                            )
                        else:
                            logger.warning(
                                f"Unknown extractor type: {data_extractor}",
                                trigger_id=trigger_id,
                            )
                    except Exception as extractor_error:
                        logger.error(
                            f"Data extractor failed: {extractor_error}",
                            trigger_id=trigger_id,
                            exc_info=True,
                        )
                        # Continue without extracted data

                # The one path every trigger kind starts its task through: it
                # evaluates the conditions, stamps provenance, records the
                # execution and counts failures toward auto-disable.
                firing = await trigger_service.fire(
                    trigger_id,
                    execution_data,
                    task_id=scheduled_task_id(correlation_id),
                    provenance=TaskProvenance(
                        origin_type="trigger",
                        origin_id=str(trigger_id),
                        correlation_id=correlation_id,
                    ),
                )

                execution_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                execution_id = firing.execution.id if firing.execution else None
                if firing.outcome == "reacted":
                    logger.info(
                        f"Trigger {trigger_id} executed successfully, task_id: {firing.task_id}"
                    )
                    return ExecuteTriggerResult(
                        trigger_id=trigger_id,
                        status=TriggerOutcome.SUCCESS,
                        task_id=firing.task_id,
                        execution_id=execution_id,
                        execution_time_ms=execution_time_ms,
                        trigger_data=execution_data,
                    )
                if firing.outcome == "skipped":
                    logger.info(f"Trigger {trigger_id} skipped: {firing.reason}")
                    return ExecuteTriggerResult(
                        trigger_id=trigger_id,
                        status=TriggerOutcome.SKIPPED,
                        reason=(
                            TriggerSkipReason.CONDITIONS_NOT_MET
                            if firing.verdict is not None
                            else TriggerSkipReason.TRIGGER_INACTIVE
                        ),
                        execution_id=execution_id,
                        execution_time_ms=execution_time_ms,
                        trigger_data=execution_data,
                    )
                logger.warning(f"Trigger {trigger_id} produced no task: {firing.reason}")
                return ExecuteTriggerResult(
                    trigger_id=trigger_id,
                    status=TriggerOutcome.FAILED,
                    execution_id=execution_id,
                    execution_time_ms=execution_time_ms,
                    error=firing.reason,
                    trigger_data=execution_data,
                )

        except Exception as e:
            from agentarea_triggers.domain.enums import ExecutionStatus
            from agentarea_triggers.trigger_service import (
                TriggerNotFoundError,
                TriggerValidationError,
            )

            if isinstance(e, TriggerNotFoundError | TriggerValidationError):
                raise

            execution_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            logger.error(f"Error executing trigger {trigger_id}: {e}", exc_info=True)

            try:
                database = get_database()
                async with database.async_session_factory() as session:
                    user_context = await _resolve_trigger_context(session, trigger_id)
                    trigger_service = _trigger_service(session, user_context)

                    await trigger_service.record_execution(
                        trigger_id=trigger_id,
                        status=ExecutionStatus.FAILED,
                        execution_time_ms=execution_time_ms,
                        error_message=str(e),
                        trigger_data=execution_data,
                    )
            except Exception as record_error:
                logger.error(
                    f"Failed to record execution failure for trigger {trigger_id}: {record_error}",
                    exc_info=True,
                )

            raise

    @activity.defn(name="record_trigger_execution_activity")
    async def record_trigger_execution_activity(
        request: RecordTriggerExecutionRequest,
    ) -> RecordTriggerExecutionResult:
        """Record a trigger execution result.

        Args:
            request: RecordTriggerExecutionRequest including trigger_id and execution_data

        Returns:
            RecordTriggerExecutionResult containing the recorded execution info
        """
        trigger_id = request.trigger_id
        execution_data = request.execution_data
        try:
            from agentarea_triggers.domain.enums import ExecutionStatus

            database = get_database()
            async with database.async_session_factory() as session:
                user_context = await _resolve_trigger_context(session, trigger_id)
                trigger_service = _trigger_service(session, user_context)

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
                    trigger_data=trigger_data,
                )

                logger.info(f"Recorded execution for trigger {trigger_id}: {status}")

                return RecordTriggerExecutionResult(
                    execution_id=execution_result.id,
                    trigger_id=trigger_id,
                    status=status.value,
                    recorded_at=execution_result.executed_at.isoformat(),
                )

        except Exception as e:
            logger.error(f"Failed to record execution for trigger {trigger_id}: {e}", exc_info=True)
            raise

    @activity.defn(name="evaluate_trigger_conditions_activity")
    async def evaluate_trigger_conditions_activity(
        request: EvaluateTriggerConditionsRequest,
    ) -> EvaluateTriggerConditionsResult:
        """Evaluate trigger conditions using LLM service.

        Args:
            request: EvaluateTriggerConditionsRequest including trigger_id and event_data

        Returns:
            EvaluateTriggerConditionsResult with evaluation outcome
        """
        trigger_id = request.trigger_id
        event_data = request.event_data
        try:
            from agentarea_triggers.trigger_service import TriggerService

            database = get_database()
            async with database.async_session_factory() as session:
                user_context = await _resolve_trigger_context(session, trigger_id)
                from agentarea_common.base.repository_factory import RepositoryFactory

                repository_factory = RepositoryFactory(session, user_context)

                trigger_service = TriggerService(
                    repository_factory=repository_factory,
                    event_broker=dependencies.event_broker,
                    llm_condition_evaluator=_condition_evaluator(session, user_context),
                )

                trigger = await trigger_service.get_trigger(trigger_id)
                if not trigger:
                    logger.warning(f"Trigger {trigger_id} not found for condition evaluation")
                    return EvaluateTriggerConditionsResult(
                        conditions_met=False, trigger_id=trigger_id
                    )

                # Use the trigger service's condition evaluation method
                conditions_met = await trigger_service.evaluate_trigger_conditions(
                    trigger, event_data
                )
                return EvaluateTriggerConditionsResult(
                    conditions_met=conditions_met, trigger_id=trigger_id
                )

        except Exception as e:
            logger.error(
                f"Error evaluating conditions for trigger {trigger_id}: {e}", exc_info=True
            )
            return EvaluateTriggerConditionsResult(conditions_met=False, trigger_id=trigger_id)

    return [
        execute_trigger_activity,
        record_trigger_execution_activity,
        evaluate_trigger_conditions_activity,
    ]
