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
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from agentarea_common.agent_status import AgentStatus
from agentarea_common.audit import audited
from agentarea_common.config import get_settings
from agentarea_common.events.base_events import EventEnvelope
from agentarea_common.events.broker import EventBroker
from agentarea_common.reserved_task_parameters import (
    FOLLOW_UP_MESSAGE_PARAMETER,
    RESERVED_TASK_PARAMETERS,
    drop_reserved_parameters,
)
from agentarea_common.trigger_event_file import (
    TRIGGER_EVENT_FILE_PARAMETER,
    TRIGGER_EVENT_PARAMETER,
)
from agentarea_streams.application.stream_service import StreamService
from agentarea_streams.domain import (
    EventFilter,
    StreamNotFoundError,
    value_at,
)
from agentarea_tasks.infrastructure.repository import TaskRepository
from pydantic import ValidationError

from .condition_models import validate_condition_models
from .delivery_address import FiringDelivery
from .domain.cron import cron_expression_error, timezone_error
from .domain.enums import ExecutionStatus, TriggerType
from .domain.models import (
    ConditionVerdict,
    CronTrigger,
    Trigger,
    TriggerBatchWindow,
    TriggerCreate,
    TriggerExecution,
    TriggerFiring,
    TriggerUpdate,
)
from .event_context import TriggerEvent, render_event_block
from .failures import TaskNotStartedError, is_permanent, is_spend_cap_refusal
from .infrastructure.repository import TriggerExecutionRepository, TriggerRepository
from .llm_condition_evaluator import (
    LLMConditionEvaluationError,
    LLMConditionEvaluator,
    condition_syntax_errors,
)
from .logging_utils import (
    DependencyUnavailableError,
    TriggerConditionError,
    TriggerExecutionError,
    TriggerLogger,
    TriggerNotFoundError,
    TriggerValidationError,
    generate_correlation_id,
    set_correlation_id,
)
from .schemas.dto import TriggerCreate as TriggerCreatePayload
from .schemas.dto import TriggerUpdate as TriggerUpdatePayload
from .temporal_schedule_manager import TemporalScheduleManager
from .trigger_validation import validate_trigger_configuration

if TYPE_CHECKING:
    from agentarea_tasks.domain.interfaces import FollowUpClaim
    from agentarea_tasks.domain.models import TaskProvenance
    from agentarea_tasks.domain.task_definitions import TaskDefinition

logger = TriggerLogger(__name__)


# Error classes moved to logging_utils.py for consistency


def _only_field_matches(conditions: dict[str, Any]) -> bool:
    """Whether the rule-based fallback can check every part of ``conditions``."""
    return set(conditions) == {"field_matches"}


# The task query is resolved here rather than at each execution path because
# there are two of them -- the service, for webhooks and manual runs, and the
# Temporal activity, for schedules and pollers -- and they had drifted apart.
NO_TASK_TEXT = (
    "Trigger has no task text: nothing arrived with the event and none is set on the trigger"
)


def event_text(trigger_data: dict[str, Any]) -> str | None:
    """The text the event itself carried -- a chat message, say -- or None.

    Text on the events that fired the trigger, else a top-level text. Events
    arrive under ``events`` or ``extracted_events`` depending on which path fired.
    """
    events = trigger_data.get("events") or trigger_data.get("extracted_events") or []
    texts = [
        event["text"]
        for event in events
        if isinstance(event, dict) and isinstance(event.get("text"), str) and event["text"].strip()
    ]
    if not texts:
        top_level_text = trigger_data.get("text")
        if isinstance(top_level_text, str) and top_level_text.strip():
            texts = [top_level_text]
    return "\n".join(texts) if texts else None


def resolve_task_query(
    trigger: Trigger,
    trigger_data: dict[str, Any],
    definition: TaskDefinition | None = None,
) -> str | None:
    """What the agent is being asked to do, or None when nothing says.

    The trigger's task text is what to do -- or, for a trigger that runs a saved
    task, that ``definition``'s text; the event is what to do it with, and
    reaches the agent whole in the block ``compose_task_input`` appends, its own
    text included. So a task text always wins. Only a trigger without one -- a
    chat channel whose every message is the request -- takes the event's text
    (see ``event_text``) as the ask.

    Returns None rather than inventing an ask. The trigger's description used to
    stand in, but it explains the automation to whoever reads the list -- running
    an agent against "every weekday at 06:45 it scores the inbound queue"
    produces a task about the schedule instead of the work.
    """
    if definition is not None:
        return definition.description.strip()
    task_text = trigger.task_parameters.get("text")
    if isinstance(task_text, str) and task_text.strip():
        return task_text.strip()
    return event_text(trigger_data)


@dataclass(frozen=True)
class TriggerTaskInput:
    """What a trigger's task asks, and the message that tells the agent what started it."""

    ask: str
    message: str
    event_file: str | None = None
    # The scrubbed data the event file holds; set with event_file.
    event_data: dict[str, Any] | None = None
    # The event's own text, which is all a follow-up into a running chat sends.
    follow_up: str | None = None

    def stamp(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Name the input file the run must provision, and what a follow-up delivers."""
        if self.event_file is not None:
            parameters[TRIGGER_EVENT_FILE_PARAMETER] = self.event_file
            parameters[TRIGGER_EVENT_PARAMETER] = self.event_data
        if self.follow_up is not None:
            parameters[FOLLOW_UP_MESSAGE_PARAMETER] = self.follow_up
        return parameters


def compose_task_input(
    trigger: Trigger,
    trigger_data: dict[str, Any],
    event: TriggerEvent | None = None,
    definition: TaskDefinition | None = None,
) -> TriggerTaskInput | None:
    """The task a firing starts: its ask, plus the event that fired it. None when nothing asks.

    Every path that fires a trigger comes through here, so the agent sees what
    started it the same way whatever the source. ``event`` is what a stream
    delivered, whose data is ``trigger_data``; without one the events a
    channel, poller or replay carried in ``trigger_data`` stand in, scrubbed,
    and a schedule tick carries none.
    """
    ask = resolve_task_query(trigger, trigger_data, definition)
    if ask is None:
        return None
    if event is None:
        event = TriggerEvent.from_trigger_data(trigger_data)
    elif event.data != trigger_data:
        raise ValueError("the event a trigger fired on must carry the trigger data it was given")
    if event is None:
        return TriggerTaskInput(ask=ask, message=ask)
    block = render_event_block(
        trigger_name=trigger.name, trigger_type=trigger.trigger_type.value, event=event
    )
    return TriggerTaskInput(
        ask=ask,
        message=f"{ask}\n\n{block.text}",
        event_file=block.event_file,
        event_data=event.data if block.event_file is not None else None,
        follow_up=event_text(trigger_data),
    )


def _validate_batch(
    batch: TriggerBatchWindow | None,
    task_parameters: dict[str, Any],
    task_definition_id: UUID | None = None,
) -> None:
    """A batch fits the deployment's cap, and says what to do with its events."""
    if batch is None:
        return
    cap = get_settings().triggers.BATCH_MAX_EVENTS
    if batch.max_events is not None and batch.max_events > cap:
        raise TriggerValidationError(
            f"batch max_events is {batch.max_events}; a batch holds at most {cap} events"
        )
    if task_definition_id is not None:
        return
    text = (task_parameters or {}).get("text")
    if not isinstance(text, str) or not text.strip():
        raise TriggerValidationError(
            "a batched trigger needs task text: what to do with the events of each batch"
        )


def _task_definition_after(existing: Trigger, update: TriggerUpdate) -> UUID | None:
    """The saved task a trigger runs once ``update`` is applied; sent as null, none."""
    if "task_definition_id" in update.model_fields_set:
        return update.task_definition_id
    return existing.task_definition_id


def _source_identity(user_id: str | None) -> str | None:
    """The person a firing came from -- who pressed "run now", or wrote the message -- if any.

    It narrows the run and is recorded; it lends the run no authority. A
    schedule or an event nobody sent leaves the run with none.
    """
    return f"user:{user_id}" if user_id else None


class TriggerService:
    """High-level service for trigger management that orchestrates persistence and lifecycle."""

    def __init__(
        self,
        repository_factory: Any,  # RepositoryFactory type
        event_broker: EventBroker,
        task_service: Any | None = None,
        llm_condition_evaluator: LLMConditionEvaluator | None = None,
        temporal_schedule_manager: TemporalScheduleManager | None = None,
        secret_manager: Any | None = None,  # BaseSecretManager for channel credentials
    ):
        """Initialize with repository factory, event broker, and optional dependencies."""
        self._secret_manager = secret_manager
        # Create repositories using factory
        self.trigger_repository = repository_factory.create_repository(TriggerRepository)
        self.trigger_execution_repository = repository_factory.create_repository(
            TriggerExecutionRepository
        )

        self.repository_factory = repository_factory
        # Whoever this service acts for: a person through the API, an agent in a
        # run, a trigger's configurer when the schedule fires it.
        self._caller = repository_factory.user_context
        self.event_broker = event_broker
        self.task_service = task_service
        self.llm_condition_evaluator = llm_condition_evaluator
        self.temporal_schedule_manager = temporal_schedule_manager
        self.stream_service = StreamService(repository_factory, get_settings().streams)

        # The model instances an LLM condition may name, read as this workspace.
        from agentarea_llm.infrastructure.model_instance_repository import (
            ModelInstanceRepository,
        )

        self.model_instance_repository = repository_factory.create_repository(
            ModelInstanceRepository
        )
        from agentarea_tasks.infrastructure.task_definition_repository import (
            TaskDefinitionRepository,
        )

        self.task_definition_repository = repository_factory.create_repository(
            TaskDefinitionRepository
        )
        self.task_repository = repository_factory.create_repository(TaskRepository)

        # Create agent repository using factory for validation
        try:
            from agentarea_agents.infrastructure.repository import AgentRepository

            self.agent_repository = repository_factory.create_repository(AgentRepository)
        except ImportError:
            self.agent_repository = None

    # CRUD Operations

    @audited("trigger.create", resource_type="trigger")
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
        # Refused before anything else, and not wrapped as a failure to create:
        # a caller who may not run the agent is told so (403).
        await self._require_may_invoke(trigger_data.agent_id)

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
            await self._validate_task_definition(
                trigger_data.task_definition_id, trigger_data.agent_id
            )

            # Create the trigger
            trigger = await self.trigger_repository.create_from_model(trigger_data)
            await self._bind_stream(trigger, trigger_data)

            logger.info(
                f"Successfully created trigger '{trigger.name}'",
                trigger_id=trigger.id,
                agent_id=trigger.agent_id,
                trigger_type=trigger.trigger_type.value,
            )

            await self._apply_schedule(trigger)

            return trigger

        except TriggerValidationError:
            logger.error(
                f"Trigger validation failed for '{trigger_data.name}'",
                agent_id=trigger_data.agent_id,
                trigger_type=trigger_data.trigger_type.value,
                exc_info=True,
            )
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error creating trigger '{trigger_data.name}': {e}",
                agent_id=trigger_data.agent_id,
                trigger_type=trigger_data.trigger_type.value,
                exc_info=True,
            )
            raise TriggerExecutionError(
                f"Failed to create trigger: {e}",
                correlation_id=correlation_id,
                trigger_name=trigger_data.name,
                agent_id=str(trigger_data.agent_id),
            ) from None

    async def _bind_stream(self, trigger: Trigger, trigger_data: TriggerCreate) -> None:
        """Subscribe a stream trigger to its stream."""
        if trigger_data.trigger_type != TriggerType.STREAM:
            return
        if trigger_data.stream_id is None:
            raise TriggerValidationError("stream_id is required for STREAM triggers")
        await self.stream_service.subscribe_trigger(
            stream_id=trigger_data.stream_id,
            trigger_id=trigger.id,
            event_filter=EventFilter.model_validate(trigger_data.event_filter or {}),
        )

    async def _sync_stream_binding(self, trigger_id: UUID, trigger_update: TriggerUpdate) -> None:
        if trigger_update.event_filter is not None:
            await self.stream_service.update_trigger_filter(
                trigger_id, EventFilter.model_validate(trigger_update.event_filter)
            )

    async def create_trigger_from_payload(
        self, payload: TriggerCreatePayload, created_by: str, workspace_id: str | None = None
    ) -> Trigger:
        """Create a trigger from the REST/MCP DTO.

        Thin wrapper around :meth:`create_trigger` that converts the
        single source-of-truth DTO (``agentarea_triggers.schemas.dto.TriggerCreate``)
        into the internal domain value object before delegating.

        Args:
            payload: The Pydantic create DTO from REST body or MCP tool kwargs.
            created_by: User id stamped onto the trigger (server-derived).
            workspace_id: Workspace id stamped onto the trigger (server-derived).

        Returns:
            The created trigger.
        """
        domain_payload = payload.to_domain(created_by=created_by, workspace_id=workspace_id)
        return await self.create_trigger(domain_payload)

    async def update_trigger_from_payload(
        self, trigger_id: UUID, payload: TriggerUpdatePayload
    ) -> Trigger:
        """Update a trigger from the REST/MCP DTO.

        Thin wrapper around :meth:`update_trigger` that converts the
        single source-of-truth DTO into the internal domain value object.
        """
        domain_payload = payload.to_domain()
        return await self.update_trigger(trigger_id, domain_payload)

    async def get_trigger(self, trigger_id: UUID) -> Trigger | None:
        """Get a trigger by ID.

        Args:
            trigger_id: The unique identifier of the trigger

        Returns:
            The trigger if found, None otherwise
        """
        return await self.trigger_repository.get_trigger(trigger_id)

    @audited("trigger.update", resource_type="trigger", resource_id_param="trigger_id")
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
        # Pointing the trigger at an agent, or switching it on, binds it.
        if trigger_update.agent_id is not None or (
            trigger_update.is_active is True and not existing_trigger.is_active
        ):
            await self._require_may_invoke(trigger_update.agent_id or existing_trigger.agent_id)

        # Update the trigger
        updated_trigger = await self.trigger_repository.update_by_id(trigger_id, trigger_update)

        if updated_trigger:
            logger.info(f"Updated trigger {trigger_id}")
            await self._sync_stream_binding(trigger_id, trigger_update)
            if trigger_update.is_active is False and existing_trigger.is_active:
                await self._close_open_batches(existing_trigger, "trigger disabled")

            if (
                trigger_update.cron_expression is not None
                or trigger_update.timezone is not None
                or trigger_update.is_active is not None
            ):
                await self._apply_schedule(updated_trigger)

        return updated_trigger

    @audited("trigger.delete", resource_type="trigger", resource_id_param="trigger_id")
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
        if existing_trigger.trigger_type == TriggerType.CRON and self.temporal_schedule_manager:
            try:
                await self.temporal_schedule_manager.delete_cron_schedule(trigger_id)
                logger.info(f"Deleted schedule for cron trigger {trigger_id}")
            except Exception as e:
                logger.error(
                    f"Failed to delete schedule for cron trigger {trigger_id}: {e}", exc_info=True
                )

        await self._close_open_batches(existing_trigger, "trigger deleted")

        # Delete the trigger (cascade will handle executions)
        success = await self.trigger_repository.delete(trigger_id)

        if success:
            logger.info(f"Deleted trigger {trigger_id}")

        return success

    async def list_triggers(
        self,
        agent_id: UUID | None = None,
        trigger_type: TriggerType | None = None,
        active_only: bool = False,
        limit: int = 100,
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
        # Build filters for the repository
        filters = {}
        if agent_id:
            filters["agent_id"] = agent_id
        if trigger_type:
            filters["trigger_type"] = trigger_type
        if active_only:
            filters["is_active"] = True

        return await self.trigger_repository.list_triggers(limit=limit, **filters)

    # Lifecycle Management

    async def enable_trigger(self, trigger_id: UUID) -> bool:
        """Enable a trigger.

        Args:
            trigger_id: The unique identifier of the trigger

        Returns:
            True if the trigger was successfully enabled, False if not found
        """
        trigger = await self.get_trigger(trigger_id)
        if trigger is not None:
            await self._require_may_invoke(trigger.agent_id)
        # Enable trigger in database
        success = await self.trigger_repository.enable_trigger(trigger_id)

        if success:
            logger.info(f"Enabled trigger {trigger_id}")

            trigger = await self.get_trigger(trigger_id)
            if trigger is not None:
                await self._apply_schedule(trigger)

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

            trigger = await self.get_trigger(trigger_id)
            if trigger is not None:
                await self._close_open_batches(trigger, "trigger disabled")
                await self._apply_schedule(trigger)

        return success

    async def _close_open_batches(self, trigger: Trigger, why: str) -> None:
        """Skip the events held in the trigger's open batches and cancel those batches."""
        if trigger.trigger_type != TriggerType.STREAM:
            return
        from .batch_firing import close_open_batches

        workflow_ids = await close_open_batches(
            self.repository_factory.session,
            self.repository_factory.user_context,
            trigger.id,
            f"{why} while the event waited in a batch",
        )
        for workflow_id in workflow_ids:
            if self.temporal_schedule_manager is None:
                logger.info(
                    f"Batch {workflow_id} of trigger {trigger.id} is not cancelled from here; "
                    "its events are skipped and it starts no task when its timer fires"
                )
                continue
            await self.temporal_schedule_manager.cancel_batch(workflow_id)

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
        fired_by: str | None = None,
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
            fired_by: Principal who asked for this run, when a person did

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
                fired_by=fired_by,
            )

            # Record the execution
            exec_data = execution.model_dump()
            exec_data["status"] = (
                exec_data["status"].value
                if hasattr(exec_data["status"], "value")
                else exec_data["status"]
            )
            recorded_execution = await self.trigger_execution_repository.create(**exec_data)

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
                    exc_info=True,
                )

            return recorded_execution

        except Exception as e:
            error_msg = f"Failed to record trigger execution: {e}"
            logger.error(
                error_msg,
                trigger_id=trigger_id,
                status=status.value,
                execution_time_ms=execution_time_ms,
                exc_info=True,
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

        if status == ExecutionStatus.SKIPPED:
            return

        trigger.record_execution_started()
        await self.trigger_repository.update_execution_tracking(
            trigger_id, last_execution_at=trigger.last_execution_at
        )
        if status != ExecutionStatus.SUCCESS:
            await self._count_failure(trigger_id)

    async def record_run_outcome(
        self, trigger_id: UUID, task_id: UUID, *, failed: bool, error: str | None = None
    ) -> None:
        """Count how a task the trigger started ended towards its failure_threshold.

        A completed task resets the count. A failed one marks the firing that
        started it failed and counts once: a redelivered outcome finds it marked.
        Raises FiringNotRecordedError while no firing names the task yet. The
        trigger's row is locked before the firing's, the order a firing takes them.
        """
        if not await self.trigger_repository.lock(trigger_id):
            logger.info(f"Trigger {trigger_id} is gone; the end of task {task_id} is not counted")
            return
        if not failed:
            await self.trigger_repository.reset_failures(trigger_id)
            return
        if await self.trigger_execution_repository.mark_run_failed(trigger_id, task_id, error):
            await self._count_failure(trigger_id)

    async def _count_failure(self, trigger_id: UUID) -> None:
        """Add one consecutive failure; reaching failure_threshold disables the trigger."""
        count = await self.trigger_repository.count_failure(trigger_id)
        if count is None or not count.active or count.failures < count.threshold:
            return
        logger.warning(
            f"Disabling trigger {trigger_id} after {count.failures} consecutive failures, "
            "its failure threshold"
        )
        await self.disable_trigger(trigger_id)
        await self._publish_trigger_auto_disabled_event(trigger_id, count.failures)

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
                EventEnvelope(
                    event_type="trigger.auto_disabled",
                    data={
                        "trigger_id": str(trigger_id),
                        "consecutive_failures": consecutive_failures,
                        "disabled_at": datetime.utcnow().isoformat(),
                        "reason": "consecutive_failures_threshold_exceeded",
                    },
                )
            )
            logger.info(f"Published auto-disabled event for trigger {trigger_id}")
        except Exception as e:
            logger.error(
                f"Failed to publish auto-disabled event for trigger {trigger_id}: {e}",
                exc_info=True,
            )

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

        await self.trigger_repository.reset_failures(trigger_id)

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

    async def _apply_schedule(self, trigger: Trigger) -> None:
        """Bring a cron trigger's schedule to the trigger as stored.

        The trigger is already written; a schedule Temporal refuses now is
        brought in line by the schedule sync within minutes (see ``schedule_sync``).
        """
        if not isinstance(trigger, CronTrigger):
            return
        if self.temporal_schedule_manager is None:
            logger.warning(
                f"No schedule manager to apply trigger {trigger.id}'s schedule; "
                "the schedule sync applies it"
            )
            return
        try:
            await self.temporal_schedule_manager.apply_cron_schedule(
                trigger.id, trigger.cron_expression, trigger.timezone, paused=not trigger.is_active
            )
        except Exception:
            logger.error(
                f"Could not bring the schedule of trigger {trigger.id} in line; "
                "the schedule sync retries it",
                exc_info=True,
            )

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
            logger.error(
                f"Failed to get schedule info for cron trigger {trigger_id}: {e}", exc_info=True
            )
            return None

    # Validation Methods

    async def _require_may_invoke(self, agent_id: UUID) -> None:
        """Refuse binding or starting ``agent_id`` unless the caller may make it act (403).

        A trigger's runs act as its agent, so wiring one is the grant to check:
        nobody sets an agent going on a schedule, or presses "run now", for an
        agent they could not start by hand. A scheduled firing asks nobody.
        """
        from agentarea_common.auth.permission import require_permission

        await require_permission("execute", "agent", str(agent_id), self._caller)

    async def agent_stands(self, agent_id: UUID) -> bool:
        """Whether the agent a trigger runs still exists in its workspace and is active."""
        if self.agent_repository is None:
            raise DependencyUnavailableError(
                "a trigger cannot fire without the agent repository",
                dependency="agent_repository",
                agent_id=str(agent_id),
            )
        agent = await self.agent_repository.get(agent_id)
        return agent is not None and agent.status == AgentStatus.ACTIVE

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
            if agent.status == AgentStatus.ARCHIVED:
                raise TriggerValidationError(
                    f"Agent {agent_id} is archived; restore it first", agent_id=str(agent_id)
                )

            logger.debug("Agent validation successful", agent_id=agent_id)

        except Exception as e:
            if isinstance(e, TriggerValidationError | DependencyUnavailableError):
                raise

            error_msg = f"Error validating agent existence: {e}"
            logger.error(error_msg, agent_id=agent_id, exc_info=True)
            raise DependencyUnavailableError(
                error_msg,
                dependency="agent_repository",
                agent_id=str(agent_id),
                original_error=str(e),
            ) from e

    async def validate_configuration(self, trigger_data: TriggerCreate) -> None:
        """Check a trigger's own configuration without touching its agent.

        Lets a caller refuse a bad trigger before it creates anything the trigger
        would hang off, such as the agent itself.

        Raises:
            TriggerValidationError: If configuration is invalid
        """
        await self._validate_trigger_configuration(trigger_data)

    async def _validate_trigger_configuration(self, trigger_data: TriggerCreate) -> None:
        """Validate trigger configuration; see ``validate_trigger_configuration``."""
        await validate_trigger_configuration(trigger_data, self.model_instance_repository)
        _validate_batch(
            trigger_data.batch, trigger_data.task_parameters, trigger_data.task_definition_id
        )
        if trigger_data.trigger_type == TriggerType.STREAM and trigger_data.stream_id:
            try:
                await self.stream_service.get_stream(trigger_data.stream_id)
            except StreamNotFoundError as error:
                raise TriggerValidationError(
                    f"Stream {trigger_data.stream_id} does not exist in this workspace"
                ) from error

    async def _validate_task_definition(self, definition_id: UUID | None, agent_id: UUID) -> None:
        """A trigger runs a saved task of its own workspace, and of its own agent."""
        if definition_id is None:
            return
        definition = await self.task_definition_repository.get_definition(definition_id)
        if definition is None:
            raise TriggerValidationError(
                f"Task definition {definition_id} does not exist in this workspace"
            )
        if definition.agent_id != agent_id:
            raise TriggerValidationError(
                f"Task definition {definition_id} runs agent {definition.agent_id}, "
                f"not the trigger's agent {agent_id}"
            )

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

        if trigger_update.agent_id is not None:
            await self._validate_agent_exists(trigger_update.agent_id)

        definition_set = "task_definition_id" in trigger_update.model_fields_set
        if definition_set or trigger_update.agent_id is not None:
            await self._validate_task_definition(
                _task_definition_after(existing_trigger, trigger_update),
                trigger_update.agent_id or existing_trigger.agent_id,
            )

        if trigger_update.cron_expression is not None:
            error = cron_expression_error(trigger_update.cron_expression)
            if error is not None:
                raise TriggerValidationError(error)
        if trigger_update.timezone is not None:
            error = timezone_error(trigger_update.timezone.strip())
            if error is not None:
                raise TriggerValidationError(error)

        if trigger_update.conditions is not None:
            await validate_condition_models(
                trigger_update.conditions, self.model_instance_repository
            )
            # An empty dict means "no conditions configured", which stays
            # legitimate; anything else must be a well-formed condition body.
            if trigger_update.conditions:
                errors = condition_syntax_errors(trigger_update.conditions)
                if errors:
                    raise TriggerValidationError("; ".join(errors))

        if (
            trigger_update.session is not None
            and existing_trigger.trigger_type != TriggerType.STREAM
        ):
            raise TriggerValidationError("session applies only to stream triggers")

        if trigger_update.batch is not None:
            if existing_trigger.trigger_type != TriggerType.STREAM:
                raise TriggerValidationError("only a stream trigger takes a batch")
            _validate_batch(
                trigger_update.batch,
                trigger_update.task_parameters
                if trigger_update.task_parameters is not None
                else existing_trigger.task_parameters,
                _task_definition_after(existing_trigger, trigger_update),
            )

        if trigger_update.event_filter is not None:
            if existing_trigger.trigger_type != TriggerType.STREAM:
                raise TriggerValidationError("event_filter applies only to stream triggers")
            try:
                EventFilter.model_validate(trigger_update.event_filter)
            except ValidationError as error:
                raise TriggerValidationError(f"event_filter: {error}") from error

        # Type-specific validation
        if isinstance(existing_trigger, CronTrigger):
            if trigger_update.cron_expression is not None:
                parts = trigger_update.cron_expression.strip().split()
                if len(parts) not in [5, 6]:
                    raise TriggerValidationError("Cron expression must have 5 or 6 parts")

            # Editing a schedule into the state create_trigger refuses is the
            # same mistake, made later. An update that leaves task_parameters
            # and the saved task alone leaves the existing text alone with them.
            if (
                trigger_update.task_parameters is not None or definition_set
            ) and _task_definition_after(existing_trigger, trigger_update) is None:
                task_parameters = (
                    trigger_update.task_parameters
                    if trigger_update.task_parameters is not None
                    else existing_trigger.task_parameters
                )
                task_text = task_parameters.get("text")
                if not isinstance(task_text, str) or not task_text.strip():
                    raise TriggerValidationError("Task text is required for CRON triggers")

    # Utility Methods

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
        self, trigger_id: UUID, trigger_data: dict[str, Any], fired_by: str | None = None
    ) -> TriggerExecution | None:
        """Execute a trigger; see ``fire`` for what each outcome means."""
        return (await self.fire(trigger_id, trigger_data, fired_by)).execution

    async def fire(
        self,
        trigger_id: UUID,
        trigger_data: dict[str, Any],
        fired_by: str | None = None,
        *,
        task_id: UUID | None = None,
        provenance: TaskProvenance | None = None,
        follow_up_claim: FollowUpClaim | None = None,
        raise_retryable: bool = False,
        event: TriggerEvent | None = None,
        caller: str | None = None,
        delivery: FiringDelivery | None = None,
        evaluate_conditions: bool = True,
    ) -> TriggerFiring:
        """Run a trigger once and say what happened.

        ``fired_by`` is set only when a person pressed "run now"; the schedule,
        inbound webhooks and stream subscriptions leave it empty. ``event`` is
        the stream event that fired it, told to the agent (see
        ``compose_task_input``). ``task_id``
        makes a retried firing idempotent: when a task with that id already
        exists, the firing reports it instead of starting another run;
        ``follow_up_claim`` does the same for a follow-up routed into a running
        workflow, which stores no task. ``provenance`` is stamped on the task
        it creates. ``caller`` is the person a messenger event came from, admitted
        before this call; the task is theirs rather than the trigger owner's.
        ``delivery`` is where a stream firing's task replies and the session it
        joins (see ``delivery_address``). A batch, whose every event met the
        conditions before it joined, fires with ``evaluate_conditions`` off.

        With ``raise_retryable`` only a permanent failure (see
        ``failures.is_permanent``) becomes an ``error`` outcome; anything else --
        infrastructure trouble, or a failure nobody classified -- raises without
        being recorded or counted towards ``failure_threshold``, because the
        caller still holds the event and retries it.

        Raises:
            TriggerNotFoundError: If trigger doesn't exist
        """
        trigger = await self.get_trigger(trigger_id)
        if not trigger:
            raise TriggerNotFoundError(f"Trigger {trigger_id} not found")

        # is_active governs the trigger's own mechanism -- whether the schedule
        # comes due, whether the webhook is accepted. It does not govern a person
        # asking for one run, and testing a trigger that is switched off (or not
        # switched on yet) is most of why they would ask.
        if not trigger.is_active and fired_by is None:
            logger.warning(f"Attempted to execute inactive trigger {trigger_id}")
            execution = await self._record_execution_skipped(
                trigger_id, "Trigger is inactive", trigger_data
            )
            return TriggerFiring(
                outcome="skipped", reason="trigger is inactive", execution=execution
            )

        # A person pressing "run now" starts the agent, so they must be allowed to.
        if fired_by is not None:
            await self._require_may_invoke(trigger.agent_id)
        # The run acts as the agent, so the agent is what must still stand when it
        # fires; whoever configured the trigger lends it nothing. A trigger whose
        # agent is gone stops once, with that reason, on every path.
        if not await self.agent_stands(trigger.agent_id):
            reason = f"agent_unavailable: agent {trigger.agent_id} is gone or inactive"
            await self.trigger_repository.mark_needs_new_owner(trigger.id)
            execution = await self._record_execution_failure(
                trigger_id, reason, trigger_data, 0, fired_by=fired_by
            )
            return TriggerFiring(outcome="error", reason=reason, execution=execution)

        definition = None
        if trigger.task_definition_id is not None:
            definition = await self.task_definition_repository.get_definition(
                trigger.task_definition_id
            )
            if definition is None:
                reason = f"Task definition {trigger.task_definition_id} no longer exists"
                execution = await self._record_execution_failure(
                    trigger_id, reason, trigger_data, fired_by=fired_by
                )
                return TriggerFiring(outcome="error", reason=reason, execution=execution)

        if task_id is not None and self.task_service:
            existing = await self.task_service.get_task(task_id)
            if existing is not None:
                if not existing.execution_id and (
                    existing.status == "pending"
                    or (raise_retryable and existing.status == "failed")
                ):
                    # An earlier attempt stored the task but did not start it:
                    # its start failed, or its process died before starting it.
                    # Starting it now is the retry. A failure raises and is retried.
                    # The stored row keeps only the ask, so the message is composed
                    # again from the same event.
                    retried_input = compose_task_input(trigger, trigger_data, event, definition)
                    if retried_input is None:
                        # The trigger lost its instruction since the first attempt;
                        # the stored ask is no longer what it would run.
                        logger.warning(
                            f"Not restarting task {task_id} for trigger {trigger_id}: "
                            f"{NO_TASK_TEXT}"
                        )
                        execution = await self._record_execution_failure(
                            trigger_id, NO_TASK_TEXT, trigger_data, fired_by=fired_by
                        )
                        return TriggerFiring(
                            outcome="error", reason=NO_TASK_TEXT, execution=execution
                        )
                    existing.query = retried_input.message
                    await self.task_service.restart_undispatched_task(existing)
                    logger.info(f"Started task {task_id} for trigger {trigger_id} on retry")
                    return TriggerFiring(
                        outcome="reacted",
                        reason="task started on retry",
                        task_id=task_id,
                        execution=await self._record_started_once(
                            trigger_id, task_id, trigger_data, fired_by
                        ),
                    )
                return TriggerFiring(
                    outcome="reacted",
                    reason="task already started",
                    task_id=task_id,
                    execution=await self._record_started_once(
                        trigger_id, task_id, trigger_data, fired_by
                    ),
                )

        # A schedule comes due again whether or not its last run has finished;
        # the firing workflow ends once the task starts, so Temporal's overlap
        # policy never sees the run. Each event of a stream trigger is its own
        # work, and a person asking for a run gets it.
        if trigger.trigger_type == TriggerType.CRON and fired_by is None:
            running = await self._run_still_going(trigger.id)
            if running is not None:
                reason = f"The previous run is still going (task {running})"
                logger.info(f"Trigger {trigger_id} skipped: {reason}")
                execution = await self._record_execution_skipped(trigger_id, reason, trigger_data)
                return TriggerFiring(
                    outcome="skipped", reason=reason, execution=execution, blocked_by=running
                )

        start_time = time.time()
        verdict: ConditionVerdict | None = None
        try:
            if trigger.conditions and evaluate_conditions:
                verdict = await self.evaluate_trigger_verdict(trigger, trigger_data)
                if not verdict.met:
                    logger.info(f"Trigger {trigger_id} conditions not met, skipping execution")
                    execution = await self._record_execution_skipped(
                        trigger_id, "Trigger conditions not met", trigger_data, fired_by=fired_by
                    )
                    return TriggerFiring(
                        outcome="skipped",
                        reason=verdict.reason,
                        verdict=verdict,
                        execution=execution,
                    )

            created_task_id = None
            if self.task_service:
                task_input = compose_task_input(trigger, trigger_data, event, definition)
                if task_input is None:
                    execution = await self._record_execution_failure(
                        trigger_id,
                        NO_TASK_TEXT,
                        trigger_data,
                        int((time.time() - start_time) * 1000),
                        fired_by=fired_by,
                    )
                    return TriggerFiring(
                        outcome="error", reason=NO_TASK_TEXT, verdict=verdict, execution=execution
                    )

                task_params = task_input.stamp(
                    await self._build_task_parameters(
                        trigger, trigger_data, fired_by, delivery, definition
                    )
                )

                from agentarea_tasks.domain.models import AgentTask, TaskProvenance

                task = AgentTask(
                    id=task_id if task_id is not None else uuid4(),
                    title=f"Trigger: {trigger.name}",
                    description=task_input.ask,
                    query=task_input.message,
                    # A manual run belongs to whoever pressed the button, not to
                    # whoever created the trigger months ago.
                    # A message belongs to whoever sent it.
                    user_id=fired_by or caller or str(trigger.created_by),
                    workspace_id=str(trigger.workspace_id),
                    agent_id=trigger.agent_id,
                    task_parameters=task_params,
                    status="submitted",
                    provenance=(
                        provenance
                        or TaskProvenance(origin_type="trigger", origin_id=str(trigger.id))
                    ).model_copy(
                        update={
                            "source_identity": _source_identity(fired_by or caller),
                            "task_definition_id": trigger.task_definition_id,
                        }
                    ),
                )
                task = await self.task_service.route_or_submit_task(
                    task, follow_up_claim=follow_up_claim
                )

                created_task_id = task.id
                if raise_retryable and task.status == "failed" and not task.execution_id:
                    # TaskService stores the task, then reports a failed start
                    # instead of raising; the stored task is started on the retry.
                    raise TaskNotStartedError(
                        f"Task {task.id} was stored but its workflow did not start: "
                        f"{(task.result or {}).get('error')}"
                    )
                if task.status == "routed":
                    logger.info(f"Routed follow-up to existing workflow for trigger {trigger_id}")
                else:
                    logger.info(f"Submitted task {created_task_id} for trigger {trigger_id}")
            else:
                logger.warning(
                    f"Task service not available, skipping task creation for trigger {trigger_id}"
                )

            execution_time_ms = int((time.time() - start_time) * 1000)
            execution = None
            try:
                execution = await self._record_execution_success(
                    trigger_id, execution_time_ms, created_task_id, trigger_data, fired_by=fired_by
                )
            except Exception as rec_err:
                logger.warning(
                    f"Failed to record execution history (task was created successfully): {rec_err}",
                    exc_info=True,
                )
            return TriggerFiring(
                outcome="reacted",
                reason=verdict.reason if verdict else None,
                verdict=verdict,
                task_id=created_task_id,
                execution=execution,
            )

        except Exception as e:
            if is_spend_cap_refusal(e):
                # A spend cap or budget turned the firing away; the trigger is not
                # failing, so the refusal is recorded without counting towards
                # failure_threshold, and a retry would be refused the same way.
                logger.info(f"Trigger {trigger_id} refused by a spend cap: {e}")
                execution = await self._record_execution_skipped(
                    trigger_id, str(e), trigger_data, fired_by=fired_by
                )
                return TriggerFiring(
                    outcome="skipped", reason=str(e), verdict=verdict, execution=execution
                )
            if raise_retryable and not is_permanent(e):
                logger.warning(
                    f"Trigger {trigger_id} failed in a way a retry may not repeat; "
                    f"the event is retried: {e}",
                    exc_info=True,
                )
                raise
            execution_time_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Error executing trigger {trigger_id}: {e}", exc_info=True)
            execution = None
            try:
                execution = await self._record_execution_failure(
                    trigger_id, str(e), trigger_data, execution_time_ms, fired_by=fired_by
                )
            except Exception as rec_err:
                logger.warning(f"Failed to record execution failure: {rec_err}", exc_info=True)
            return TriggerFiring(
                outcome="error", reason=str(e), verdict=verdict, execution=execution
            )

    async def _run_still_going(self, trigger_id: UUID) -> UUID | None:
        """The trigger's task whose workflow is still open, if any.

        A stored status can outlive its run -- a terminated workflow, a lost
        history, a status write that failed -- so the workflow is asked; a task
        whose workflow never started is running nothing.
        """
        for task_id, workflow_id in await self.task_repository.unfinished_runs_from(
            "trigger", str(trigger_id)
        ):
            if workflow_id is None:
                continue
            if self.temporal_schedule_manager is None:
                return task_id
            if await self.temporal_schedule_manager.workflow_is_open(workflow_id):
                return task_id
        return None

    async def _record_execution_success(
        self,
        trigger_id: UUID,
        execution_time_ms: int,
        task_id: UUID | None = None,
        trigger_data: dict[str, Any] | None = None,
        fired_by: str | None = None,
    ) -> TriggerExecution:
        """Record successful trigger execution.

        Args:
            trigger_id: The trigger ID
            execution_time_ms: Execution time in milliseconds
            task_id: Optional task ID if a task was created
            trigger_data: Optional trigger data
            fired_by: Principal who asked for this run, when a person did

        Returns:
            Execution record
        """
        return await self.record_execution(
            trigger_id=trigger_id,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=execution_time_ms,
            task_id=task_id,
            trigger_data=trigger_data or {},
            fired_by=fired_by,
        )

    async def _record_started_once(
        self,
        trigger_id: UUID,
        task_id: UUID,
        trigger_data: dict[str, Any],
        fired_by: str | None,
    ) -> TriggerExecution | None:
        """Record the firing of a task an earlier attempt started, unless it recorded it.

        An attempt can start the task and die before recording its firing; the
        task's end is counted against that record.
        """
        if await self.trigger_execution_repository.names_task(trigger_id, task_id):
            return None
        return await self._record_execution_success(
            trigger_id, 0, task_id, trigger_data, fired_by=fired_by
        )

    async def _record_execution_skipped(
        self,
        trigger_id: UUID,
        reason: str,
        trigger_data: dict[str, Any] | None = None,
        fired_by: str | None = None,
    ) -> TriggerExecution:
        """Record a firing that was turned away without starting a task."""
        return await self.record_execution(
            trigger_id=trigger_id,
            status=ExecutionStatus.SKIPPED,
            execution_time_ms=0,
            error_message=reason,
            trigger_data=trigger_data or {},
            fired_by=fired_by,
        )

    async def _record_execution_failure(
        self,
        trigger_id: UUID,
        error_message: str,
        trigger_data: dict[str, Any] | None = None,
        execution_time_ms: int = 0,
        fired_by: str | None = None,
    ) -> TriggerExecution:
        """Record failed trigger execution.

        Args:
            trigger_id: The trigger ID
            error_message: Error message
            trigger_data: Optional trigger data
            execution_time_ms: Execution time in milliseconds
            fired_by: Principal who asked for this run, when a person did

        Returns:
            Execution record
        """
        return await self.record_execution(
            trigger_id=trigger_id,
            status=ExecutionStatus.FAILED,
            execution_time_ms=execution_time_ms,
            error_message=error_message,
            trigger_data=trigger_data or {},
            fired_by=fired_by,
        )

    async def _build_task_parameters(
        self,
        trigger: Trigger,
        trigger_data: dict[str, Any],
        fired_by: str | None = None,
        delivery: FiringDelivery | None = None,
        definition: TaskDefinition | None = None,
    ) -> dict[str, Any]:
        """Build task parameters from trigger and execution data using LLM extraction.

        Args:
            trigger: The trigger
            trigger_data: Trigger execution data
            fired_by: Principal who asked for this run, when a person did
            delivery: Where a stream firing's task replies and the session it joins
            definition: The saved task the trigger runs, whose parameters replace its own

        Returns:
            Task parameters
        """
        # Start with the asked task parameters. Reserved keys stored there
        # predate the create/update check; only the firing's delivery below may
        # name where replies go and the session, and only compose_task_input the
        # event file and the follow-up message.
        asked = definition.parameters if definition is not None else trigger.task_parameters
        params = dict(drop_reserved_parameters(asked) or {})

        # Add trigger metadata
        params.update(
            {
                "trigger_id": str(trigger.id),
                "trigger_type": trigger.trigger_type.value,
                "trigger_name": trigger.name,
                "execution_time": datetime.utcnow().isoformat(),
            }
        )

        # Present only on a manual run, so the task listing can say a person asked
        # for this one rather than reporting it as the schedule coming due.
        if fired_by is not None:
            params["fired_by"] = fired_by

        # Add trigger data
        if trigger_data:
            params["trigger_data"] = trigger_data

        if delivery is not None:
            delivery.stamp(params)

        # Use LLM to extract additional parameters if instruction is provided
        llm_instruction = asked.get("llm_parameter_extraction")
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

                # Event-derived data cannot grant new capabilities or file access.
                resource_keys = {"mcps", "mcp", "mcp_servers", "skills", "files"}
                for key, value in llm_params.items():
                    if (
                        key not in params
                        and key not in resource_keys
                        and key not in RESERVED_TASK_PARAMETERS
                    ):
                        params[key] = value

                logger.info(
                    f"Enhanced task parameters with LLM extraction for trigger {trigger.id}"
                )

            except Exception as e:
                logger.warning(
                    f"LLM parameter extraction failed for trigger {trigger.id}: {e}", exc_info=True
                )
                # Continue with basic parameters

        return params

    async def evaluate_trigger_verdict(
        self, trigger: Trigger, event_data: dict[str, Any]
    ) -> ConditionVerdict:
        """Evaluate trigger conditions against event data using LLM-powered evaluation.

        Args:
            trigger: The trigger to evaluate
            event_data: Event data to evaluate against

        Returns:
            The structured verdict: whether conditions are met, and why.

        Raises:
            TriggerConditionError: The conditions could not be evaluated. A
                condition nobody could check is not a condition that passed.
        """
        if not trigger.conditions:
            return ConditionVerdict(verdict="met", reason="trigger has no conditions")

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
                return await self.llm_condition_evaluator.evaluate_structured(
                    condition=trigger.conditions,
                    event_data=event_data,
                    trigger_context=trigger_context,
                )

            # Without an evaluator only field_matches can be checked; any other
            # condition would be reported as met without having been looked at.
            if not _only_field_matches(trigger.conditions):
                raise TriggerConditionError(
                    "Trigger conditions need the condition evaluator, which is not "
                    "available on this path",
                    trigger_id=str(trigger.id),
                )
            return await self._evaluate_simple_conditions(trigger.conditions, event_data)

        except TriggerConditionError:
            raise

        except LLMConditionEvaluationError as e:
            logger.error(
                f"LLM condition evaluation failed for trigger {trigger.id}: {e}", exc_info=True
            )
            # The rule-based evaluator only checks field_matches; for anything
            # else it would report a pass without having looked.
            if not _only_field_matches(trigger.conditions):
                raise TriggerConditionError(
                    f"Trigger conditions could not be evaluated: {e}", trigger_id=str(trigger.id)
                ) from e
            try:
                return await self._evaluate_simple_conditions(trigger.conditions, event_data)
            except Exception as fallback_error:
                logger.error(
                    f"Fallback condition evaluation also failed for trigger {trigger.id}: "
                    f"{fallback_error}",
                    exc_info=True,
                )
                raise TriggerConditionError(
                    f"Trigger conditions could not be evaluated: {fallback_error}",
                    trigger_id=str(trigger.id),
                ) from fallback_error

        except Exception as e:
            logger.error(
                f"Error evaluating conditions for trigger {trigger.id}: {e}", exc_info=True
            )
            raise TriggerConditionError(
                f"Trigger conditions could not be evaluated: {e}", trigger_id=str(trigger.id)
            ) from e

    async def evaluate_trigger_conditions(
        self, trigger: Trigger, event_data: dict[str, Any]
    ) -> bool:
        """Whether the trigger's conditions are met; see ``evaluate_trigger_verdict``."""
        return (await self.evaluate_trigger_verdict(trigger, event_data)).met

    def _get_nested_value(self, data: dict[str, Any], field_path: str) -> Any:
        """The value at a dotted ``field_path`` in ``data``, or ``None``."""
        return value_at(data, field_path)

    async def _evaluate_simple_conditions(
        self, conditions: dict[str, Any], event_data: dict[str, Any]
    ) -> ConditionVerdict:
        """Evaluate simple rule-based conditions as fallback.

        Args:
            conditions: Condition configuration
            event_data: Event data to evaluate

        Returns:
            The verdict, with a reason naming the field that failed to match.

        Raises:
            TriggerConditionError: ``conditions`` names nothing this fallback
                can check. A condition nobody looked at is not a condition
                that passed.
        """
        if "field_matches" not in conditions:
            raise TriggerConditionError("Conditions have no 'field_matches' to check")
        for field_path, expected_value in conditions["field_matches"].items():
            actual_value = self._get_nested_value(event_data, field_path)
            if actual_value != expected_value:
                return ConditionVerdict(
                    verdict="not_met",
                    reason=f"{field_path} is {actual_value!r}, not {expected_value!r}",
                )
        return ConditionVerdict(verdict="met", reason="every field_matches entry matched")

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
            return await self.llm_condition_evaluator.extract_task_parameters(
                instruction=instruction, event_data=event_data, trigger_context=trigger_context
            )
        except Exception as e:
            logger.error(f"LLM parameter extraction failed: {e}", exc_info=True)
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

    async def get_execution_metrics(
        self, trigger_id: UUID, hours: int | None = 24
    ) -> dict[str, Any]:
        """Get execution metrics for a trigger.

        Args:
            trigger_id: The trigger ID
            hours: Time period in hours; ``None`` covers the trigger's whole history

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
