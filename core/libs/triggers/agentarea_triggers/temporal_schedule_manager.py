"""Temporal Schedule Manager for cron trigger scheduling.

This module provides a clean interface for managing Temporal Schedules
for cron triggers, handling schedule creation, updates, and deletion.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleSpec,
    ScheduleState,
    ScheduleUpdate,
)
from temporalio.exceptions import TemporalError

from .logging_utils import (
    DependencyUnavailableError,
    TriggerExecutionError,
    TriggerLogger,
    generate_correlation_id,
    set_correlation_id,
)

logger = TriggerLogger(__name__)


class TemporalScheduleManager:
    """Manages Temporal Schedules for cron triggers."""

    def __init__(self, temporal_client: Client):
        """Initialize with Temporal client.

        Args:
            temporal_client: The Temporal client instance
        """
        self.client = temporal_client

    async def create_cron_schedule(
        self, trigger_id: UUID, cron_expression: str, timezone: str = "UTC"
    ) -> str:
        """Create a Temporal Schedule for a cron trigger.

        Args:
            trigger_id: The ID of the trigger
            cron_expression: The cron expression for scheduling
            timezone: The timezone for the cron expression

        Returns:
            The schedule ID that was created

        Raises:
            TriggerExecutionError: If schedule creation fails
            DependencyUnavailableError: If Temporal client is unavailable
        """
        correlation_id = generate_correlation_id()
        set_correlation_id(correlation_id)
        schedule_id = f"cron-trigger-{trigger_id}"

        if not self.client:
            error_msg = "Temporal client not available"
            logger.error(error_msg, trigger_id=trigger_id)
            raise DependencyUnavailableError(
                error_msg, dependency="temporal_client", trigger_id=str(trigger_id)
            )

        try:
            logger.info(
                "Creating Temporal schedule for cron trigger",
                trigger_id=trigger_id,
                schedule_id=schedule_id,
                cron_expression=cron_expression,
                timezone=timezone,
            )

            # Create the schedule
            schedule = Schedule(
                action=ScheduleActionStartWorkflow(
                    "TriggerExecutionWorkflow",
                    args=[
                        trigger_id,
                        {
                            "execution_time": datetime.utcnow().isoformat(),
                            "source": "cron",
                            "cron_expression": cron_expression,
                            "timezone": timezone,
                        },
                    ],
                    id=f"trigger-execution-{trigger_id}-{{.ScheduledTime}}",
                    task_queue="trigger-execution-queue",
                ),
                spec=ScheduleSpec(cron_expressions=[cron_expression], timezone=timezone),
                state=ScheduleState(
                    note=f"Cron trigger schedule for trigger {trigger_id}", paused=False
                ),
            )

            await self.client.create_schedule(schedule_id=schedule_id, schedule=schedule)

            logger.info(
                "Successfully created Temporal schedule",
                trigger_id=trigger_id,
                schedule_id=schedule_id,
                cron_expression=cron_expression,
            )
            return schedule_id

        except TemporalError as e:
            error_msg = f"Temporal error creating schedule: {e}"
            logger.error(
                error_msg,
                trigger_id=trigger_id,
                schedule_id=schedule_id,
                cron_expression=cron_expression,
            )
            raise TriggerExecutionError(
                error_msg,
                trigger_id=str(trigger_id),
                schedule_id=schedule_id,
                original_error=str(e),
            ) from None
        except Exception as e:
            error_msg = f"Unexpected error creating schedule: {e}"
            logger.error(
                error_msg,
                trigger_id=trigger_id,
                schedule_id=schedule_id,
                cron_expression=cron_expression,
            )
            raise TriggerExecutionError(
                error_msg,
                trigger_id=str(trigger_id),
                schedule_id=schedule_id,
                original_error=str(e),
            ) from None

    async def update_cron_schedule(
        self, trigger_id: UUID, cron_expression: str, timezone: str = "UTC"
    ) -> None:
        """Update an existing Temporal Schedule for a cron trigger.

        Args:
            trigger_id: The ID of the trigger
            cron_expression: The new cron expression
            timezone: The new timezone

        Raises:
            Exception: If schedule update fails
        """
        schedule_id = f"cron-trigger-{trigger_id}"

        try:
            # Get the schedule handle
            handle = self.client.get_schedule_handle(schedule_id)

            # Update the schedule
            await handle.update(
                updater=lambda input: ScheduleUpdate(
                    schedule=Schedule(
                        action=ScheduleActionStartWorkflow(
                            "TriggerExecutionWorkflow",
                            args=[
                                trigger_id,
                                {
                                    "execution_time": datetime.utcnow().isoformat(),
                                    "source": "cron",
                                    "cron_expression": cron_expression,
                                    "timezone": timezone,
                                },
                            ],
                            id=f"trigger-execution-{trigger_id}-{{.ScheduledTime}}",
                            task_queue="trigger-execution-queue",
                        ),
                        spec=ScheduleSpec(cron_expressions=[cron_expression], timezone=timezone),
                        state=input.description.schedule.state,
                    )
                )
            )

            logger.info(f"Updated Temporal schedule {schedule_id} for trigger {trigger_id}")

        except Exception as e:
            logger.error(f"Failed to update schedule for trigger {trigger_id}: {e}")
            raise

    async def delete_cron_schedule(self, trigger_id: UUID) -> None:
        """Delete a Temporal Schedule for a cron trigger.

        Args:
            trigger_id: The ID of the trigger

        Raises:
            Exception: If schedule deletion fails
        """
        schedule_id = f"cron-trigger-{trigger_id}"

        try:
            # Get the schedule handle
            handle = self.client.get_schedule_handle(schedule_id)

            # Delete the schedule
            await handle.delete()

            logger.info(f"Deleted Temporal schedule {schedule_id} for trigger {trigger_id}")

        except TemporalError as e:
            if "not found" in str(e).lower():
                logger.warning(f"Schedule {schedule_id} not found, may have been already deleted")
            else:
                logger.error(f"Failed to delete schedule for trigger {trigger_id}: {e}")
                raise
        except Exception as e:
            logger.error(f"Failed to delete schedule for trigger {trigger_id}: {e}")
            raise

    async def pause_cron_schedule(self, trigger_id: UUID) -> None:
        """Pause a Temporal Schedule for a cron trigger.

        Args:
            trigger_id: The ID of the trigger

        Raises:
            Exception: If schedule pause fails
        """
        schedule_id = f"cron-trigger-{trigger_id}"

        try:
            # Get the schedule handle
            handle = self.client.get_schedule_handle(schedule_id)

            # Pause the schedule
            await handle.pause(note=f"Trigger {trigger_id} disabled")

            logger.info(f"Paused Temporal schedule {schedule_id} for trigger {trigger_id}")

        except Exception as e:
            logger.error(f"Failed to pause schedule for trigger {trigger_id}: {e}")
            raise

    async def unpause_cron_schedule(self, trigger_id: UUID) -> None:
        """Unpause a Temporal Schedule for a cron trigger.

        Args:
            trigger_id: The ID of the trigger

        Raises:
            Exception: If schedule unpause fails
        """
        schedule_id = f"cron-trigger-{trigger_id}"

        try:
            # Get the schedule handle
            handle = self.client.get_schedule_handle(schedule_id)

            # Unpause the schedule
            await handle.unpause(note=f"Trigger {trigger_id} enabled")

            logger.info(f"Unpaused Temporal schedule {schedule_id} for trigger {trigger_id}")

        except Exception as e:
            logger.error(f"Failed to unpause schedule for trigger {trigger_id}: {e}")
            raise

    async def get_schedule_info(self, trigger_id: UUID) -> dict[str, Any] | None:
        """Get information about a Temporal Schedule.

        Args:
            trigger_id: The ID of the trigger

        Returns:
            Dictionary containing schedule information, or None if not found
        """
        schedule_id = f"cron-trigger-{trigger_id}"

        try:
            # Get the schedule handle
            handle = self.client.get_schedule_handle(schedule_id)

            # Get schedule description
            description = await handle.describe()

            return {
                "schedule_id": schedule_id,
                "trigger_id": str(trigger_id),
                "cron_expressions": description.schedule.spec.cron_expressions,
                "timezone": description.schedule.spec.timezone,
                "paused": description.schedule.state.paused,
                "note": description.schedule.state.note,
                "next_action_times": [t.isoformat() for t in description.info.next_action_times],
                "recent_actions": [
                    {
                        "scheduled_time": action.scheduled_time.isoformat(),
                        "actual_time": action.actual_time.isoformat(),
                        "start_workflow_result": str(action.start_workflow_result)
                        if action.start_workflow_result
                        else None,
                    }
                    for action in description.info.recent_actions
                ],
            }

        except TemporalError as e:
            if "not found" in str(e).lower():
                return None
            else:
                logger.error(f"Failed to get schedule info for trigger {trigger_id}: {e}")
                raise
        except Exception as e:
            logger.error(f"Failed to get schedule info for trigger {trigger_id}: {e}")
            raise
