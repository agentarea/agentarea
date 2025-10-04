"""Unit tests for trigger safety mechanisms.

Tests the business logic safety features including:
- Automatic trigger disabling after consecutive failures
- Failure count tracking and reset
- Safety status monitoring
- Event publishing for auto-disabled triggers
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_triggers.domain.enums import ExecutionStatus
from agentarea_triggers.domain.models import (
    CronTrigger,
    TriggerExecution,
)
from agentarea_triggers.trigger_service import (
    TriggerService,
)


class TestTriggerSafetyMechanisms:
    """Test cases for trigger safety mechanisms."""

    @pytest.fixture
    def mock_trigger_repository(self):
        """Mock trigger repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_trigger_execution_repository(self):
        """Mock trigger execution repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_event_broker(self):
        """Mock event broker."""
        return AsyncMock()

    @pytest.fixture
    def mock_agent_repository(self):
        """Mock agent repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_task_service(self):
        """Mock task service."""
        return AsyncMock()

    @pytest.fixture
    def mock_temporal_schedule_manager(self):
        """Mock temporal schedule manager."""
        return AsyncMock()

    @pytest.fixture
    def trigger_service(
        self,
        mock_trigger_repository,
        mock_trigger_execution_repository,
        mock_event_broker,
        mock_agent_repository,
        mock_task_service,
        mock_temporal_schedule_manager,
    ):
        """Create TriggerService instance with mocked dependencies."""
        return TriggerService(
            trigger_repository=mock_trigger_repository,
            trigger_execution_repository=mock_trigger_execution_repository,
            event_broker=mock_event_broker,
            agent_repository=mock_agent_repository,
            task_service=mock_task_service,
            llm_condition_evaluator=None,
            temporal_schedule_manager=mock_temporal_schedule_manager,
        )

    @pytest.fixture
    def sample_agent_id(self):
        """Sample agent ID."""
        return uuid4()

    @pytest.fixture
    def sample_trigger_with_failures(self, sample_agent_id):
        """Sample trigger with some failures."""
        now = datetime.utcnow()
        return CronTrigger(
            id=uuid4(),
            name="Test Trigger",
            description="Test trigger for safety mechanisms",
            agent_id=sample_agent_id,
            cron_expression="0 9 * * *",
            timezone="UTC",
            created_by="test_user",
            failure_threshold=5,
            consecutive_failures=3,  # 3 out of 5 failures
            created_at=now - timedelta(minutes=20),  # Created 20 minutes ago
            updated_at=now - timedelta(minutes=10),  # Updated 10 minutes ago
            last_execution_at=now - timedelta(minutes=10),  # Last executed 10 minutes ago
        )

    @pytest.fixture
    def sample_trigger_at_threshold(self, sample_agent_id):
        """Sample trigger at failure threshold."""
        now = datetime.utcnow()
        return CronTrigger(
            id=uuid4(),
            name="Failing Trigger",
            description="Trigger at failure threshold",
            agent_id=sample_agent_id,
            cron_expression="0 9 * * *",
            timezone="UTC",
            created_by="test_user",
            failure_threshold=5,
            consecutive_failures=5,  # At threshold
            created_at=now - timedelta(minutes=15),  # Created 15 minutes ago
            updated_at=now - timedelta(minutes=5),  # Updated 5 minutes ago
            last_execution_at=now - timedelta(minutes=5),  # Last executed 5 minutes ago
        )

    # Test Automatic Trigger Disabling

    @pytest.mark.asyncio
    async def test_record_execution_success_resets_failures(
        self,
        trigger_service,
        mock_trigger_repository,
        mock_trigger_execution_repository,
        sample_trigger_with_failures,
    ):
        """Test that successful execution resets consecutive failures."""
        # Setup mocks
        execution = TriggerExecution(
            trigger_id=sample_trigger_with_failures.id,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=100,
        )
        mock_trigger_execution_repository.create.return_value = execution
        mock_trigger_repository.get.return_value = sample_trigger_with_failures
        mock_trigger_repository.update.return_value = sample_trigger_with_failures

        # Execute
        result = await trigger_service.record_execution(
            trigger_id=sample_trigger_with_failures.id,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=100,
        )

        # Verify
        assert result.status == ExecutionStatus.SUCCESS
        assert sample_trigger_with_failures.consecutive_failures == 0  # Reset to 0
        mock_trigger_repository.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_execution_failure_increments_count(
        self,
        trigger_service,
        mock_trigger_repository,
        mock_trigger_execution_repository,
        sample_trigger_with_failures,
    ):
        """Test that failed execution increments consecutive failures."""
        # Setup mocks
        initial_failures = sample_trigger_with_failures.consecutive_failures
        execution = TriggerExecution(
            trigger_id=sample_trigger_with_failures.id,
            status=ExecutionStatus.FAILED,
            execution_time_ms=100,
            error_message="Test error",
        )
        mock_trigger_execution_repository.create.return_value = execution
        mock_trigger_repository.get.return_value = sample_trigger_with_failures
        mock_trigger_repository.update.return_value = sample_trigger_with_failures
        mock_trigger_repository.disable_trigger.return_value = True

        # Execute
        result = await trigger_service.record_execution(
            trigger_id=sample_trigger_with_failures.id,
            status=ExecutionStatus.FAILED,
            execution_time_ms=100,
            error_message="Test error",
        )

        # Verify
        assert result.status == ExecutionStatus.FAILED
        assert sample_trigger_with_failures.consecutive_failures == initial_failures + 1
        mock_trigger_repository.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_auto_disabled_at_threshold(
        self,
        trigger_service,
        mock_trigger_repository,
        mock_trigger_execution_repository,
        mock_event_broker,
        sample_trigger_at_threshold,
    ):
        """Test that trigger is automatically disabled when reaching failure threshold."""
        # Setup mocks
        execution = TriggerExecution(
            trigger_id=sample_trigger_at_threshold.id,
            status=ExecutionStatus.FAILED,
            execution_time_ms=100,
            error_message="Final failure",
        )
        mock_trigger_execution_repository.create.return_value = execution
        mock_trigger_repository.get.return_value = sample_trigger_at_threshold
        mock_trigger_repository.update.return_value = sample_trigger_at_threshold
        mock_trigger_repository.disable_trigger.return_value = True

        # Execute
        await trigger_service.record_execution(
            trigger_id=sample_trigger_at_threshold.id,
            status=ExecutionStatus.FAILED,
            execution_time_ms=100,
            error_message="Final failure",
        )

        # Verify trigger was disabled
        mock_trigger_repository.disable_trigger.assert_called_once_with(
            sample_trigger_at_threshold.id
        )

        # Verify auto-disabled event was published
        mock_event_broker.publish.assert_called_once()
        call_args = mock_event_broker.publish.call_args
        assert call_args[1]["event_type"] == "trigger.auto_disabled"
        assert call_args[1]["data"]["trigger_id"] == str(sample_trigger_at_threshold.id)
        assert call_args[1]["data"]["consecutive_failures"] == 6  # 5 + 1
        assert call_args[1]["data"]["reason"] == "consecutive_failures_threshold_exceeded"

    @pytest.mark.asyncio
    async def test_trigger_not_disabled_below_threshold(
        self,
        trigger_service,
        mock_trigger_repository,
        mock_trigger_execution_repository,
        sample_trigger_with_failures,
    ):
        """Test that trigger is not disabled when below failure threshold."""
        # Setup mocks
        execution = TriggerExecution(
            trigger_id=sample_trigger_with_failures.id,
            status=ExecutionStatus.FAILED,
            execution_time_ms=100,
            error_message="Another failure",
        )
        mock_trigger_execution_repository.create.return_value = execution
        mock_trigger_repository.get.return_value = sample_trigger_with_failures
        mock_trigger_repository.update.return_value = sample_trigger_with_failures

        # Execute
        await trigger_service.record_execution(
            trigger_id=sample_trigger_with_failures.id,
            status=ExecutionStatus.FAILED,
            execution_time_ms=100,
            error_message="Another failure",
        )

        # Verify trigger was NOT disabled (still below threshold)
        mock_trigger_repository.disable_trigger.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_publish_failure_does_not_break_execution(
        self,
        trigger_service,
        mock_trigger_repository,
        mock_trigger_execution_repository,
        mock_event_broker,
        sample_trigger_at_threshold,
    ):
        """Test that event publishing failure doesn't break trigger execution recording."""
        # Setup mocks
        execution = TriggerExecution(
            trigger_id=sample_trigger_at_threshold.id,
            status=ExecutionStatus.FAILED,
            execution_time_ms=100,
            error_message="Final failure",
        )
        mock_trigger_execution_repository.create.return_value = execution
        mock_trigger_repository.get.return_value = sample_trigger_at_threshold
        mock_trigger_repository.update.return_value = sample_trigger_at_threshold
        mock_trigger_repository.disable_trigger.return_value = True

        # Make event broker fail
        mock_event_broker.publish.side_effect = Exception("Event broker error")

        # Execute - should not raise exception
        result = await trigger_service.record_execution(
            trigger_id=sample_trigger_at_threshold.id,
            status=ExecutionStatus.FAILED,
            execution_time_ms=100,
            error_message="Final failure",
        )

        # Verify execution was still recorded despite event failure
        assert result.status == ExecutionStatus.FAILED
        mock_trigger_repository.disable_trigger.assert_called_once()

    # Test Failure Count Reset

    @pytest.mark.asyncio
    async def test_reset_trigger_failure_count_success(
        self, trigger_service, mock_trigger_repository, sample_trigger_with_failures
    ):
        """Test successful reset of trigger failure count."""
        # Setup mocks
        mock_trigger_repository.get.return_value = sample_trigger_with_failures
        mock_trigger_repository.update.return_value = sample_trigger_with_failures

        # Execute
        result = await trigger_service.reset_trigger_failure_count(sample_trigger_with_failures.id)

        # Verify
        assert result is True
        assert sample_trigger_with_failures.consecutive_failures == 0
        mock_trigger_repository.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_trigger_failure_count_not_found(
        self, trigger_service, mock_trigger_repository
    ):
        """Test reset failure count when trigger doesn't exist."""
        # Setup mocks
        trigger_id = uuid4()
        mock_trigger_repository.get.return_value = None

        # Execute
        result = await trigger_service.reset_trigger_failure_count(trigger_id)

        # Verify
        assert result is False
        mock_trigger_repository.update.assert_not_called()

    # Test Safety Status Monitoring

    @pytest.mark.asyncio
    async def test_get_trigger_safety_status_success(
        self, trigger_service, mock_trigger_repository, sample_trigger_with_failures
    ):
        """Test getting trigger safety status."""
        # Setup mocks
        mock_trigger_repository.get.return_value = sample_trigger_with_failures

        # Execute
        result = await trigger_service.get_trigger_safety_status(sample_trigger_with_failures.id)

        # Verify
        assert result is not None
        assert result["trigger_id"] == str(sample_trigger_with_failures.id)
        assert result["consecutive_failures"] == 3
        assert result["failure_threshold"] == 5
        assert result["failures_until_disable"] == 2  # 5 - 3
        assert result["is_at_risk"] is False  # 3 < (5 * 0.8) = 4, so False
        assert result["should_disable"] is False  # Not at threshold yet
        assert result["last_execution_at"] is not None

    @pytest.mark.asyncio
    async def test_get_trigger_safety_status_at_risk(
        self, trigger_service, mock_trigger_repository, sample_agent_id
    ):
        """Test safety status for trigger at risk (80% of threshold)."""
        # Create trigger at 80% of threshold (4 out of 5)
        trigger_at_risk = CronTrigger(
            id=uuid4(),
            name="At Risk Trigger",
            agent_id=sample_agent_id,
            cron_expression="0 9 * * *",
            timezone="UTC",
            created_by="test_user",
            failure_threshold=5,
            consecutive_failures=4,  # 4 out of 5 = 80%
        )

        # Setup mocks
        mock_trigger_repository.get.return_value = trigger_at_risk

        # Execute
        result = await trigger_service.get_trigger_safety_status(trigger_at_risk.id)

        # Verify
        assert result["is_at_risk"] is True  # 4 >= (5 * 0.8) = 4
        assert result["failures_until_disable"] == 1
        assert result["should_disable"] is False

    @pytest.mark.asyncio
    async def test_get_trigger_safety_status_should_disable(
        self, trigger_service, mock_trigger_repository, sample_trigger_at_threshold
    ):
        """Test safety status for trigger that should be disabled."""
        # Setup mocks
        mock_trigger_repository.get.return_value = sample_trigger_at_threshold

        # Execute
        result = await trigger_service.get_trigger_safety_status(sample_trigger_at_threshold.id)

        # Verify
        assert result["should_disable"] is True
        assert result["failures_until_disable"] == 0
        assert result["is_at_risk"] is True

    @pytest.mark.asyncio
    async def test_get_trigger_safety_status_not_found(
        self, trigger_service, mock_trigger_repository
    ):
        """Test safety status when trigger doesn't exist."""
        # Setup mocks
        trigger_id = uuid4()
        mock_trigger_repository.get.return_value = None

        # Execute
        result = await trigger_service.get_trigger_safety_status(trigger_id)

        # Verify
        assert result is None

    # Test Domain Model Safety Logic

    def test_trigger_should_disable_due_to_failures_true(self, sample_trigger_at_threshold):
        """Test trigger domain model correctly identifies when it should be disabled."""
        assert sample_trigger_at_threshold.should_disable_due_to_failures() is True

    def test_trigger_should_disable_due_to_failures_false(self, sample_trigger_with_failures):
        """Test trigger domain model correctly identifies when it should not be disabled."""
        assert sample_trigger_with_failures.should_disable_due_to_failures() is False

    def test_trigger_record_execution_success_resets_count(self, sample_trigger_with_failures):
        """Test trigger domain model resets failure count on success."""
        initial_failures = sample_trigger_with_failures.consecutive_failures
        assert initial_failures > 0

        sample_trigger_with_failures.record_execution_success()

        assert sample_trigger_with_failures.consecutive_failures == 0
        assert sample_trigger_with_failures.last_execution_at is not None

    def test_trigger_record_execution_failure_increments_count(self, sample_trigger_with_failures):
        """Test trigger domain model increments failure count on failure."""
        initial_failures = sample_trigger_with_failures.consecutive_failures

        sample_trigger_with_failures.record_execution_failure()

        assert sample_trigger_with_failures.consecutive_failures == initial_failures + 1
        assert sample_trigger_with_failures.last_execution_at is not None

    # Test Edge Cases

    @pytest.mark.asyncio
    async def test_update_execution_tracking_trigger_not_found(
        self, trigger_service, mock_trigger_repository
    ):
        """Test execution tracking update when trigger doesn't exist."""
        # Setup mocks
        trigger_id = uuid4()
        mock_trigger_repository.get.return_value = None

        # Execute - should not raise exception
        await trigger_service._update_trigger_execution_tracking(
            trigger_id, ExecutionStatus.SUCCESS
        )

        # Verify no update was attempted
        mock_trigger_repository.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_custom_failure_threshold(
        self, trigger_service, mock_trigger_repository, sample_agent_id
    ):
        """Test trigger with custom failure threshold."""
        # Create trigger with custom threshold
        custom_trigger = CronTrigger(
            id=uuid4(),
            name="Custom Threshold Trigger",
            agent_id=sample_agent_id,
            cron_expression="0 9 * * *",
            timezone="UTC",
            created_by="test_user",
            failure_threshold=3,  # Custom threshold
            consecutive_failures=2,  # One less than threshold
        )

        # Setup mocks
        mock_trigger_repository.get.return_value = custom_trigger

        # Execute
        result = await trigger_service.get_trigger_safety_status(custom_trigger.id)

        # Verify
        assert result["failure_threshold"] == 3
        assert result["failures_until_disable"] == 1
        assert result["is_at_risk"] is False  # 2 < (3 * 0.8) = 2.4, so False

    @pytest.mark.asyncio
    async def test_zero_consecutive_failures(
        self, trigger_service, mock_trigger_repository, sample_agent_id
    ):
        """Test trigger with zero consecutive failures."""
        # Create trigger with no failures
        clean_trigger = CronTrigger(
            id=uuid4(),
            name="Clean Trigger",
            agent_id=sample_agent_id,
            cron_expression="0 9 * * *",
            timezone="UTC",
            created_by="test_user",
            failure_threshold=5,
            consecutive_failures=0,  # No failures
        )

        # Setup mocks
        mock_trigger_repository.get.return_value = clean_trigger

        # Execute
        result = await trigger_service.get_trigger_safety_status(clean_trigger.id)

        # Verify
        assert result["consecutive_failures"] == 0
        assert result["failures_until_disable"] == 5
        assert result["is_at_risk"] is False
        assert result["should_disable"] is False
