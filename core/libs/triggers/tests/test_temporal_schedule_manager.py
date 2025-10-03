"""Unit tests for TemporalScheduleManager."""

from datetime import datetime
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
from temporalio.exceptions import ScheduleNotFoundError


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
        """Test creating a new schedule."""
        # Setup mocks
        mock_temporal_client.get_schedule_handle.side_effect = ScheduleNotFoundError("Not found")

        # Execute
        await schedule_manager.create_schedule(sample_cron_trigger)

        # Verify
        mock_temporal_client.create_schedule.assert_called_once()
        schedule_id = f"cron-trigger-{sample_cron_trigger.id}"

        # Verify schedule ID
        args, kwargs = mock_temporal_client.create_schedule.call_args
        assert kwargs["schedule_id"] == schedule_id

        # Verify schedule spec
        schedule = kwargs["schedule"]
        assert isinstance(schedule, Schedule)
        assert schedule.spec.cron_expressions == [sample_cron_trigger.cron_expression]
        assert schedule.spec.timezone == sample_cron_trigger.timezone

        # Verify workflow action
        action = schedule.action
        assert isinstance(action, ScheduleActionStartWorkflow)
        assert action.workflow_type == "TriggerExecutionWorkflow"
        assert action.args[0] == str(sample_cron_trigger.id)
        assert action.task_queue == "trigger-task-queue"

    @pytest.mark.asyncio
    async def test_create_schedule_existing(
        self, schedule_manager, mock_temporal_client, sample_cron_trigger
    ):
        """Test creating a schedule that already exists."""
        # Setup mocks
        mock_handle = AsyncMock(spec=ScheduleHandle)
        mock_temporal_client.get_schedule_handle.return_value = mock_handle

        # Execute
        await schedule_manager.create_schedule(sample_cron_trigger)

        # Verify
        mock_temporal_client.create_schedule.assert_not_called()
        mock_handle.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_schedule(
        self, schedule_manager, mock_temporal_client, sample_cron_trigger
    ):
        """Test updating an existing schedule."""
        # Setup mocks
        mock_handle = AsyncMock(spec=ScheduleHandle)
        mock_description = MagicMock()
        mock_description.schedule = Schedule(
            action=ScheduleActionStartWorkflow(
                "TriggerExecutionWorkflow",
                args=[str(sample_cron_trigger.id), {}],
                id=f"trigger-execution-{sample_cron_trigger.id}",
                task_queue="trigger-task-queue",
            ),
            spec=ScheduleSpec(
                cron_expressions=["0 8 * * *"],  # Different cron expression
                timezone="UTC",
            ),
            state=ScheduleState(paused=True, note="Old note"),
        )
        mock_handle.describe.return_value = mock_description
        mock_temporal_client.get_schedule_handle.return_value = mock_handle

        # Execute
        await schedule_manager.update_schedule(sample_cron_trigger)

        # Verify
        mock_handle.update.assert_called_once()

        # Verify updated schedule
        args, kwargs = mock_handle.update.call_args
        updated_schedule = args[0]
        assert updated_schedule.spec.cron_expressions == [sample_cron_trigger.cron_expression]
        assert updated_schedule.spec.timezone == sample_cron_trigger.timezone
        assert updated_schedule.state.paused is False  # Should be active
        assert updated_schedule.state.note == f"Trigger: {sample_cron_trigger.name}"

    @pytest.mark.asyncio
    async def test_delete_schedule(self, schedule_manager, mock_temporal_client):
        """Test deleting a schedule."""
        # Setup mocks
        mock_handle = AsyncMock(spec=ScheduleHandle)
        mock_temporal_client.get_schedule_handle.return_value = mock_handle
        trigger_id = uuid4()

        # Execute
        await schedule_manager.delete_schedule(trigger_id)

        # Verify
        schedule_id = f"cron-trigger-{trigger_id}"
        mock_temporal_client.get_schedule_handle.assert_called_once_with(schedule_id)
        mock_handle.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_schedule_not_found(self, schedule_manager, mock_temporal_client):
        """Test deleting a schedule that doesn't exist."""
        # Setup mocks
        mock_temporal_client.get_schedule_handle.side_effect = ScheduleNotFoundError("Not found")
        trigger_id = uuid4()

        # Execute - should not raise exception
        await schedule_manager.delete_schedule(trigger_id)

        # Verify
        schedule_id = f"cron-trigger-{trigger_id}"
        mock_temporal_client.get_schedule_handle.assert_called_once_with(schedule_id)

    @pytest.mark.asyncio
    async def test_pause_schedule(self, schedule_manager, mock_temporal_client):
        """Test pausing a schedule."""
        # Setup mocks
        mock_handle = AsyncMock(spec=ScheduleHandle)
        mock_temporal_client.get_schedule_handle.return_value = mock_handle
        trigger_id = uuid4()

        # Execute
        await schedule_manager.pause_schedule(trigger_id)

        # Verify
        schedule_id = f"cron-trigger-{trigger_id}"
        mock_temporal_client.get_schedule_handle.assert_called_once_with(schedule_id)
        mock_handle.pause.assert_called_once_with("Trigger disabled")

    @pytest.mark.asyncio
    async def test_unpause_schedule(self, schedule_manager, mock_temporal_client):
        """Test unpausing a schedule."""
        # Setup mocks
        mock_handle = AsyncMock(spec=ScheduleHandle)
        mock_temporal_client.get_schedule_handle.return_value = mock_handle
        trigger_id = uuid4()

        # Execute
        await schedule_manager.unpause_schedule(trigger_id)

        # Verify
        schedule_id = f"cron-trigger-{trigger_id}"
        mock_temporal_client.get_schedule_handle.assert_called_once_with(schedule_id)
        mock_handle.unpause.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_schedule_status(self, schedule_manager, mock_temporal_client):
        """Test getting schedule status."""
        # Setup mocks
        mock_handle = AsyncMock(spec=ScheduleHandle)
        mock_description = MagicMock()
        mock_description.schedule = Schedule(
            action=ScheduleActionStartWorkflow(
                "TriggerExecutionWorkflow",
                args=["trigger_id", {}],
                id="trigger-execution-id",
                task_queue="trigger-task-queue",
            ),
            spec=ScheduleSpec(cron_expressions=["0 9 * * *"], timezone="UTC"),
            state=ScheduleState(paused=False, note="Trigger: Test"),
        )
        mock_description.info = MagicMock(
            next_execution_time=datetime.utcnow(),
            last_completion_time=datetime.utcnow(),
            recent_executions=[],
            created_time=datetime.utcnow(),
            last_updated_time=datetime.utcnow(),
        )
        mock_handle.describe.return_value = mock_description
        mock_temporal_client.get_schedule_handle.return_value = mock_handle
        trigger_id = uuid4()

        # Execute
        result = await schedule_manager.get_schedule_status(trigger_id)

        # Verify
        schedule_id = f"cron-trigger-{trigger_id}"
        mock_temporal_client.get_schedule_handle.assert_called_once_with(schedule_id)
        mock_handle.describe.assert_called_once()

        # Verify result
        assert result["schedule_id"] == schedule_id
        assert "is_paused" in result
        assert "next_run_time" in result
        assert "last_run_time" in result
