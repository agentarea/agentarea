"""Unit tests for TemporalScheduleManager."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_triggers.domain.enums import TriggerType
from agentarea_triggers.domain.models import CronTrigger
from agentarea_triggers.temporal_schedule_manager import TemporalScheduleManager
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleHandle,
    ScheduleSpec,
    ScheduleState,
)
from temporalio.exceptions import TemporalError


class TestTemporalScheduleManager:
    """Test cases for TemporalScheduleManager."""

    @pytest.fixture
    def mock_temporal_client(self):
        """Mock Temporal client."""
        client = AsyncMock()
        return client

    @pytest.fixture
    def schedule_manager(self, mock_temporal_client):
        """Create TemporalScheduleManager with mocked client."""
        return TemporalScheduleManager(mock_temporal_client)

    @pytest.fixture
    def sample_cron_trigger(self):
        """Sample cron trigger."""
        return CronTrigger(
            id=uuid4(),
            name="Daily Report",
            description="Generate daily report",
            agent_id=uuid4(),
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            timezone="UTC",
            created_by="test_user",
            task_parameters={"report_type": "daily"},
        )

    @pytest.mark.asyncio
    async def test_create_schedule_new(
        self, schedule_manager, mock_temporal_client, sample_cron_trigger
    ):
        """Test creating a new cron schedule.

        The redesigned API takes ``(trigger_id, cron_expression, timezone)``,
        calls ``client.create_schedule(id=..., schedule=...)`` directly (no
        check-then-update branch) and returns the schedule id.
        """
        # Execute
        schedule_id = await schedule_manager.create_cron_schedule(
            trigger_id=sample_cron_trigger.id,
            cron_expression=sample_cron_trigger.cron_expression,
            timezone=sample_cron_trigger.timezone,
        )

        # Verify
        expected_schedule_id = f"cron-trigger-{sample_cron_trigger.id}"
        assert schedule_id == expected_schedule_id
        mock_temporal_client.create_schedule.assert_called_once()

        # Verify schedule id and spec passed via keyword args
        _args, kwargs = mock_temporal_client.create_schedule.call_args
        assert kwargs["id"] == expected_schedule_id

        schedule = kwargs["schedule"]
        assert isinstance(schedule, Schedule)
        assert schedule.spec.cron_expressions == [sample_cron_trigger.cron_expression]
        assert schedule.spec.time_zone_name == sample_cron_trigger.timezone

        # Verify workflow action
        action = schedule.action
        assert isinstance(action, ScheduleActionStartWorkflow)
        assert action.workflow == "TriggerExecutionWorkflow"
        assert action.args[0] == sample_cron_trigger.id
        assert action.task_queue == "trigger-execution-queue"

    @pytest.mark.asyncio
    async def test_create_schedule_existing(
        self, schedule_manager, mock_temporal_client, sample_cron_trigger
    ):
        """Test creating a schedule when Temporal reports it already exists.

        The redesigned API has no check-then-update branch: a Temporal error
        (e.g. schedule already exists) propagates as ``TriggerExecutionError``.
        """
        from agentarea_triggers.logging_utils import TriggerExecutionError

        mock_temporal_client.create_schedule.side_effect = TemporalError(
            "schedule already exists"
        )

        with pytest.raises(TriggerExecutionError):
            await schedule_manager.create_cron_schedule(
                trigger_id=sample_cron_trigger.id,
                cron_expression=sample_cron_trigger.cron_expression,
                timezone=sample_cron_trigger.timezone,
            )

    @pytest.mark.asyncio
    async def test_update_schedule(
        self, schedule_manager, mock_temporal_client, sample_cron_trigger
    ):
        """Test updating an existing cron schedule.

        ``update_cron_schedule`` takes ``(trigger_id, cron_expression,
        timezone)`` and applies the change through the schedule handle's
        ``update`` updater callback.
        """
        # Setup mocks
        mock_handle = AsyncMock(spec=ScheduleHandle)
        mock_temporal_client.get_schedule_handle = MagicMock(return_value=mock_handle)

        # Execute
        await schedule_manager.update_cron_schedule(
            trigger_id=sample_cron_trigger.id,
            cron_expression=sample_cron_trigger.cron_expression,
            timezone=sample_cron_trigger.timezone,
        )

        # Verify the handle was resolved and update invoked
        schedule_id = f"cron-trigger-{sample_cron_trigger.id}"
        mock_temporal_client.get_schedule_handle.assert_called_once_with(schedule_id)
        mock_handle.update.assert_called_once()

        # Verify the updater produces a schedule with the new spec
        _args, kwargs = mock_handle.update.call_args
        updater = kwargs["updater"]

        update_input = MagicMock()
        update_input.description.schedule.state = ScheduleState(
            paused=True, note="Old note"
        )
        schedule_update = updater(update_input)
        updated_schedule = schedule_update.schedule
        assert updated_schedule.spec.cron_expressions == [sample_cron_trigger.cron_expression]
        assert updated_schedule.spec.time_zone_name == sample_cron_trigger.timezone

    @pytest.mark.asyncio
    async def test_delete_schedule(self, schedule_manager, mock_temporal_client):
        """Test deleting a schedule."""
        # Setup mocks
        mock_handle = AsyncMock()
        mock_temporal_client.get_schedule_handle = MagicMock(return_value=mock_handle)
        trigger_id = uuid4()

        # Execute
        await schedule_manager.delete_cron_schedule(trigger_id)

        # Verify
        schedule_id = f"cron-trigger-{trigger_id}"
        mock_temporal_client.get_schedule_handle.assert_called_once_with(schedule_id)
        mock_handle.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_schedule_not_found(self, schedule_manager, mock_temporal_client):
        """Test deleting a schedule that doesn't exist.

        The manager treats a Temporal ``not found`` error as a no-op (logs a
        warning, does not re-raise).
        """
        # Setup mocks - handle.delete raises a "not found" TemporalError
        mock_handle = AsyncMock()
        mock_handle.delete.side_effect = TemporalError("schedule not found")
        mock_temporal_client.get_schedule_handle = MagicMock(return_value=mock_handle)
        trigger_id = uuid4()

        # Execute - should not raise exception
        await schedule_manager.delete_cron_schedule(trigger_id)

        # Verify
        schedule_id = f"cron-trigger-{trigger_id}"
        mock_temporal_client.get_schedule_handle.assert_called_once_with(schedule_id)
        mock_handle.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_pause_schedule(self, schedule_manager, mock_temporal_client):
        """Test pausing a schedule."""
        # Setup mocks
        mock_handle = AsyncMock()
        mock_temporal_client.get_schedule_handle = MagicMock(return_value=mock_handle)
        trigger_id = uuid4()

        # Execute
        await schedule_manager.pause_cron_schedule(trigger_id)

        # Verify
        schedule_id = f"cron-trigger-{trigger_id}"
        mock_temporal_client.get_schedule_handle.assert_called_once_with(schedule_id)
        mock_handle.pause.assert_called_once_with(note=f"Trigger {trigger_id} disabled")

    @pytest.mark.asyncio
    async def test_unpause_schedule(self, schedule_manager, mock_temporal_client):
        """Test unpausing a schedule."""
        # Setup mocks
        mock_handle = AsyncMock()
        mock_temporal_client.get_schedule_handle = MagicMock(return_value=mock_handle)
        trigger_id = uuid4()

        # Execute
        await schedule_manager.unpause_cron_schedule(trigger_id)

        # Verify
        schedule_id = f"cron-trigger-{trigger_id}"
        mock_temporal_client.get_schedule_handle.assert_called_once_with(schedule_id)
        mock_handle.unpause.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_schedule_status(self, schedule_manager, mock_temporal_client):
        """Test getting schedule info.

        ``get_schedule_status`` was renamed to ``get_schedule_info`` and returns
        a different key set: ``schedule_id``, ``trigger_id``,
        ``cron_expressions``, ``timezone``, ``paused``, ``note``,
        ``next_action_times`` and ``recent_actions``.
        """
        # Setup mocks
        mock_handle = AsyncMock(spec=ScheduleHandle)
        mock_description = MagicMock()
        mock_description.schedule = Schedule(
            action=ScheduleActionStartWorkflow(
                "TriggerExecutionWorkflow",
                args=["trigger_id", {}],
                id="trigger-execution-id",
                task_queue="trigger-execution-queue",
            ),
            spec=ScheduleSpec(cron_expressions=["0 9 * * *"], time_zone_name="UTC"),
            state=ScheduleState(paused=False, note="Trigger: Test"),
        )
        mock_description.info = MagicMock(
            next_action_times=[],
            recent_actions=[],
        )
        mock_handle.describe.return_value = mock_description
        mock_temporal_client.get_schedule_handle = MagicMock(return_value=mock_handle)
        trigger_id = uuid4()

        # Execute
        result = await schedule_manager.get_schedule_info(trigger_id)

        # Verify
        schedule_id = f"cron-trigger-{trigger_id}"
        mock_temporal_client.get_schedule_handle.assert_called_once_with(schedule_id)
        mock_handle.describe.assert_called_once()

        # Verify result
        assert result["schedule_id"] == schedule_id
        assert result["trigger_id"] == str(trigger_id)
        assert result["cron_expressions"] == ["0 9 * * *"]
        assert result["timezone"] == "UTC"
        assert result["paused"] is False
        assert result["note"] == "Trigger: Test"
        assert result["next_action_times"] == []
        assert result["recent_actions"] == []
