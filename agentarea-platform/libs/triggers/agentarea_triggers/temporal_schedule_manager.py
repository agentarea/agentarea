"""Temporal Schedule Manager for cron trigger scheduling.

This module provides a clean interface for managing Temporal Schedules
for cron triggers, handling schedule creation, updates, and deletion.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
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

DEFAULT_TASK_QUEUE = "trigger-execution-queue"


class TemporalScheduleManager:
    """Manages Temporal Schedules for cron triggers.

    Can be initialized with either a pre-built Client or with
    namespace/task_queue for lazy client creation.
    """

    def __init__(
        self,
        temporal_client: Client | None = None,
        *,
        namespace: str = "default",
        task_queue: str = DEFAULT_TASK_QUEUE,
    ):
        self.client = temporal_client
        self._namespace = namespace
        self._task_queue = task_queue
        self._connected = temporal_client is not None

    async def _ensure_client(self) -> Client:
        """Lazily connect to Temporal if not already connected."""
        if self._connected and self.client is not None:
            return self.client
        from agentarea_common.config import get_settings

        settings = get_settings()
        server_url = settings.workflow.TEMPORAL_SERVER_URL
        if not server_url:
            raise DependencyUnavailableError(
                "TEMPORAL_SERVER_URL not configured",
                dependency="temporal_client",
            )
        from temporalio.contrib.pydantic import pydantic_data_converter

        self.client = await Client.connect(
            server_url,
            namespace=self._namespace,
            data_converter=pydantic_data_converter,
        )
        self._connected = True
        return self.client

    async def is_healthy(self) -> bool:
        """Return whether Temporal schedule operations can reach a client."""
        try:
            await self._ensure_client()
            return self.client is not None
        except Exception as e:
            logger.warning(f"Temporal schedule manager health check failed: {e}")
            return False

    async def get_active_schedule_count(self) -> int:
        """Count active trigger schedules when the Temporal client supports listing."""
        await self._ensure_client()
        if not self.client:
            return 0

        list_schedules = getattr(cast(Any, self.client), "list_schedules", None)
        if not list_schedules:
            return 0

        # Client.list_schedules() is a coroutine returning an async iterator, so
        # it must be awaited before iterating. Without the await this raised
        # "'async for' requires an object with __aiter__ method, got coroutine"
        # against a real server; mocked tests hid it.
        count = 0
        async for description in await list_schedules():
            schedule_id = getattr(description, "id", "")
            if str(schedule_id).startswith("cron-trigger-"):
                count += 1
        return count

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

        await self._ensure_client()

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
                    task_queue=self._task_queue,
                ),
                spec=ScheduleSpec(cron_expressions=[cron_expression], time_zone_name=timezone),
                state=ScheduleState(
                    note=f"Cron trigger schedule for trigger {trigger_id}", paused=False
                ),
            )

            await self.client.create_schedule(id=schedule_id, schedule=schedule)

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
        client = await self._ensure_client()
        schedule_id = f"cron-trigger-{trigger_id}"

        try:
            # Get the schedule handle
            handle = client.get_schedule_handle(schedule_id)

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
                            task_queue=self._task_queue,
                        ),
                        spec=ScheduleSpec(
                            cron_expressions=[cron_expression], time_zone_name=timezone
                        ),
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
        client = await self._ensure_client()
        schedule_id = f"cron-trigger-{trigger_id}"

        try:
            # Get the schedule handle
            handle = client.get_schedule_handle(schedule_id)

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
        client = await self._ensure_client()
        schedule_id = f"cron-trigger-{trigger_id}"

        try:
            # Get the schedule handle
            handle = client.get_schedule_handle(schedule_id)

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
        client = await self._ensure_client()
        schedule_id = f"cron-trigger-{trigger_id}"

        try:
            # Get the schedule handle
            handle = client.get_schedule_handle(schedule_id)

            # Unpause the schedule
            await handle.unpause(note=f"Trigger {trigger_id} enabled")

            logger.info(f"Unpaused Temporal schedule {schedule_id} for trigger {trigger_id}")

        except Exception as e:
            logger.error(f"Failed to unpause schedule for trigger {trigger_id}: {e}")
            raise

    def _cron_expressions_from_description(self, description: Any) -> list[str]:
        """Recover the cron expression(s) a schedule was created with.

        Temporal normalises ``cron_expressions`` into a structured calendar spec
        server-side, so ``description.schedule.spec.cron_expressions`` is empty
        after a round-trip through ``describe()``. The original expression still
        survives in the workflow action args, where ``create_cron_schedule``
        embeds it as ``{"cron_expression": ...}``; recover it from there when the
        spec no longer carries it.
        """
        spec_crons = list(getattr(description.schedule.spec, "cron_expressions", []) or [])
        if spec_crons:
            return spec_crons

        action = getattr(description.schedule, "action", None)
        args = getattr(action, "args", None) or []
        if len(args) < 2:
            return []

        payload = args[1]
        # Action args come back as raw payloads from a real server, but already
        # decoded (e.g. a plain dict) from mocked tests -- handle both.
        if not isinstance(payload, dict):
            if self.client is None:
                return []
            try:
                payload = self.client.data_converter.payload_converter.from_payloads([payload])[0]
            except Exception:
                return []

        if isinstance(payload, dict):
            cron = payload.get("cron_expression")
            if cron:
                return [cron]
        return []

    async def get_schedule_info(self, trigger_id: UUID) -> dict[str, Any] | None:
        """Get information about a Temporal Schedule.

        Args:
            trigger_id: The ID of the trigger

        Returns:
            Dictionary containing schedule information, or None if not found
        """
        client = await self._ensure_client()
        schedule_id = f"cron-trigger-{trigger_id}"

        try:
            # Get the schedule handle
            handle = client.get_schedule_handle(schedule_id)

            # Get schedule description
            description = await handle.describe()

            return {
                "schedule_id": schedule_id,
                "trigger_id": str(trigger_id),
                "cron_expressions": self._cron_expressions_from_description(description),
                "timezone": str(description.schedule.spec.time_zone_name or ""),
                "paused": bool(description.schedule.state.paused),
                "note": str(description.schedule.state.note or ""),
                "next_action_times": [
                    t.isoformat() for t in (description.info.next_action_times or [])
                ],
                "recent_actions": [
                    {
                        "scheduled_time": scheduled.isoformat()
                        if (scheduled := getattr(action, "scheduled_time", None))
                        else None,
                        "actual_time": actual.isoformat()
                        if (actual := getattr(action, "actual_time", None))
                        else None,
                        "start_workflow_result": str(getattr(action, "start_workflow_result", ""))
                        if getattr(action, "start_workflow_result", None)
                        else None,
                    }
                    for action in (description.info.recent_actions or [])
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
