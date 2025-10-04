"""Integration tests for trigger safety mechanisms and auto-disabling.

This module tests the safety mechanisms that protect the system from
runaway triggers, including auto-disabling, failure tracking, and
recovery mechanisms.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

# Import trigger system components
try:
    from agentarea_triggers.domain.enums import ExecutionStatus, TriggerType, WebhookType
    from agentarea_triggers.domain.models import (
        CronTrigger,
        TriggerCreate,
        TriggerExecution,
        WebhookTrigger,
    )
    from agentarea_triggers.infrastructure.repository import (
        TriggerExecutionRepository,
        TriggerRepository,
    )
    from agentarea_triggers.trigger_service import TriggerService

    TRIGGERS_AVAILABLE = True
except ImportError:
    TRIGGERS_AVAILABLE = False
    pytest.skip("Triggers not available", allow_module_level=True)

from agentarea_common.events.broker import EventBroker
from agentarea_tasks.task_service import TaskService

pytestmark = pytest.mark.asyncio


class TestTriggerSafetyIntegration:
    """Integration tests for trigger safety mechanisms."""

    @pytest.fixture
    def mock_event_broker(self):
        """Mock event broker for testing."""
        return AsyncMock(spec=EventBroker)

    @pytest.fixture
    def mock_task_service(self):
        """Mock task service for testing."""
        return AsyncMock(spec=TaskService)

    @pytest.fixture
    def mock_agent_repository(self):
        """Mock agent repository for testing."""
        agent_repo = AsyncMock()

        # Mock agent existence check
        mock_agent = MagicMock()
        mock_agent.id = uuid4()
        mock_agent.name = "Safety Test Agent"
        agent_repo.get.return_value = mock_agent

        return agent_repo

    @pytest.fixture
    async def trigger_repositories(self, db_session):
        """Create real trigger repositories for testing."""
        trigger_repo = TriggerRepository(db_session)
        execution_repo = TriggerExecutionRepository(db_session)
        return trigger_repo, execution_repo

    @pytest.fixture
    async def trigger_service(
        self, trigger_repositories, mock_event_broker, mock_agent_repository, mock_task_service
    ):
        """Create trigger service with real repositories."""
        trigger_repo, execution_repo = trigger_repositories

        return TriggerService(
            trigger_repository=trigger_repo,
            trigger_execution_repository=execution_repo,
            event_broker=mock_event_broker,
            agent_repository=mock_agent_repository,
            task_service=mock_task_service,
            llm_condition_evaluator=None,
            temporal_schedule_manager=None,
        )

    @pytest.fixture
    def sample_agent_id(self):
        """Sample agent ID for testing."""
        return uuid4()

    # Auto-Disable Integration Tests

    async def test_trigger_auto_disable_after_consecutive_failures(
        self, trigger_service, mock_task_service, mock_event_broker, sample_agent_id
    ):
        """Test that trigger is automatically disabled after consecutive failures."""
        # Create trigger with low failure threshold for testing
        trigger_data = TriggerCreate(
            name="Auto-Disable Test Trigger",
            description="Test trigger auto-disable functionality",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            failure_threshold=3,  # Low threshold for testing
            task_parameters={"auto_disable_test": True},
            created_by="safety_test",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        trigger_id = trigger.id

        # Verify trigger starts active
        assert trigger.is_active is True
        assert trigger.consecutive_failures == 0

        # Make task service fail
        mock_task_service.create_task_from_params.side_effect = Exception("Task service failure")

        # Execute trigger multiple times to reach failure threshold
        execution_results = []
        for i in range(3):  # Reach the threshold
            execution_data = {"execution_time": datetime.utcnow().isoformat(), "attempt": i + 1}
            result = await trigger_service.execute_trigger(trigger_id, execution_data)
            execution_results.append(result)

            # Verify each execution failed
            assert result.status == ExecutionStatus.FAILED
            assert "Task service failure" in result.error_message

        # Verify trigger was auto-disabled after reaching threshold
        updated_trigger = await trigger_service.get_trigger(trigger_id)
        assert updated_trigger.is_active is False
        assert updated_trigger.consecutive_failures == 3

        # Verify auto-disabled event was published
        mock_event_broker.publish.assert_called()
        event_call = mock_event_broker.publish.call_args
        assert event_call.kwargs["event_type"] == "trigger.auto_disabled"
        assert event_call.kwargs["data"]["trigger_id"] == str(trigger_id)
        assert event_call.kwargs["data"]["consecutive_failures"] == 3
        assert event_call.kwargs["data"]["reason"] == "consecutive_failures_threshold_exceeded"

    async def test_trigger_failure_count_reset_on_success(
        self, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test that failure count resets on successful execution."""
        # Create trigger
        trigger_data = TriggerCreate(
            name="Failure Reset Test Trigger",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            failure_threshold=5,
            created_by="failure_reset_test",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        trigger_id = trigger.id

        # Cause some failures (but not enough to auto-disable)
        mock_task_service.create_task_from_params.side_effect = Exception("Temporary failure")

        for i in range(3):  # 3 failures (less than threshold of 5)
            execution_data = {"execution_time": datetime.utcnow().isoformat()}
            result = await trigger_service.execute_trigger(trigger_id, execution_data)
            assert result.status == ExecutionStatus.FAILED

        # Verify failures accumulated
        trigger_after_failures = await trigger_service.get_trigger(trigger_id)
        assert trigger_after_failures.consecutive_failures == 3
        assert trigger_after_failures.is_active is True  # Still active

        # Fix task service and execute successfully
        mock_task_service.create_task_from_params.side_effect = None
        mock_task = MagicMock()
        mock_task.id = uuid4()
        mock_task_service.create_task_from_params.return_value = mock_task

        execution_data = {"execution_time": datetime.utcnow().isoformat()}
        success_result = await trigger_service.execute_trigger(trigger_id, execution_data)
        assert success_result.status == ExecutionStatus.SUCCESS

        # Verify failure count was reset
        trigger_after_success = await trigger_service.get_trigger(trigger_id)
        assert trigger_after_success.consecutive_failures == 0
        assert trigger_after_success.is_active is True

    async def test_multiple_triggers_independent_failure_tracking(
        self, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test that multiple triggers have independent failure tracking."""
        # Create multiple triggers
        triggers = []
        for i in range(3):
            trigger_data = TriggerCreate(
                name=f"Independent Failure Test Trigger {i}",
                agent_id=sample_agent_id,
                trigger_type=TriggerType.CRON,
                cron_expression=f"0 {9 + i} * * *",
                failure_threshold=3,
                created_by="independent_test",
            )
            trigger = await trigger_service.create_trigger(trigger_data)
            triggers.append(trigger)

        # Make task service fail for first trigger only
        def selective_failure(*args, **kwargs):
            task_params = kwargs.get("task_parameters", {})
            trigger_name = task_params.get("trigger_name", "")
            if "Trigger 0" in trigger_name:
                raise Exception("Selective failure")
            else:
                mock_task = MagicMock()
                mock_task.id = uuid4()
                return mock_task

        mock_task_service.create_task_from_params.side_effect = selective_failure

        # Execute all triggers multiple times
        for attempt in range(4):  # Exceed threshold for trigger 0
            for trigger in triggers:
                execution_data = {
                    "execution_time": datetime.utcnow().isoformat(),
                    "attempt": attempt,
                }
                await trigger_service.execute_trigger(trigger.id, execution_data)

        # Verify only first trigger was auto-disabled
        for i, trigger in enumerate(triggers):
            updated_trigger = await trigger_service.get_trigger(trigger.id)
            if i == 0:
                # First trigger should be disabled due to failures
                assert updated_trigger.is_active is False
                assert updated_trigger.consecutive_failures >= 3
            else:
                # Other triggers should remain active
                assert updated_trigger.is_active is True
                assert updated_trigger.consecutive_failures == 0

    async def test_trigger_safety_status_monitoring(
        self, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test trigger safety status monitoring and risk assessment."""
        # Create trigger
        trigger_data = TriggerCreate(
            name="Safety Status Test Trigger",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            failure_threshold=5,
            created_by="safety_status_test",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        trigger_id = trigger.id

        # Initial safety status (healthy)
        safety_status = await trigger_service.get_trigger_safety_status(trigger_id)
        assert safety_status["consecutive_failures"] == 0
        assert safety_status["failure_threshold"] == 5
        assert safety_status["failures_until_disable"] == 5
        assert safety_status["is_at_risk"] is False
        assert safety_status["should_disable"] is False

        # Cause some failures
        mock_task_service.create_task_from_params.side_effect = Exception("Test failure")

        # 2 failures (not at risk yet)
        for i in range(2):
            execution_data = {"execution_time": datetime.utcnow().isoformat()}
            await trigger_service.execute_trigger(trigger_id, execution_data)

        safety_status = await trigger_service.get_trigger_safety_status(trigger_id)
        assert safety_status["consecutive_failures"] == 2
        assert safety_status["failures_until_disable"] == 3
        assert safety_status["is_at_risk"] is False  # 2 < (5 * 0.8) = 4

        # 2 more failures (now at risk)
        for i in range(2):
            execution_data = {"execution_time": datetime.utcnow().isoformat()}
            await trigger_service.execute_trigger(trigger_id, execution_data)

        safety_status = await trigger_service.get_trigger_safety_status(trigger_id)
        assert safety_status["consecutive_failures"] == 4
        assert safety_status["failures_until_disable"] == 1
        assert safety_status["is_at_risk"] is True  # 4 >= (5 * 0.8) = 4
        assert safety_status["should_disable"] is False  # Not at threshold yet

        # 1 more failure (should disable)
        execution_data = {"execution_time": datetime.utcnow().isoformat()}
        await trigger_service.execute_trigger(trigger_id, execution_data)

        safety_status = await trigger_service.get_trigger_safety_status(trigger_id)
        assert safety_status["consecutive_failures"] == 5
        assert safety_status["failures_until_disable"] == 0
        assert safety_status["should_disable"] is True

    async def test_trigger_failure_count_reset_functionality(
        self, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test manual failure count reset functionality."""
        # Create trigger
        trigger_data = TriggerCreate(
            name="Failure Reset Test",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            failure_threshold=5,
            created_by="reset_test",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        trigger_id = trigger.id

        # Cause some failures
        mock_task_service.create_task_from_params.side_effect = Exception("Test failure")

        for i in range(3):
            execution_data = {"execution_time": datetime.utcnow().isoformat()}
            await trigger_service.execute_trigger(trigger_id, execution_data)

        # Verify failures accumulated
        trigger_with_failures = await trigger_service.get_trigger(trigger_id)
        assert trigger_with_failures.consecutive_failures == 3

        # Reset failure count
        reset_result = await trigger_service.reset_trigger_failure_count(trigger_id)
        assert reset_result is True

        # Verify failure count was reset
        trigger_after_reset = await trigger_service.get_trigger(trigger_id)
        assert trigger_after_reset.consecutive_failures == 0

        # Verify trigger remains active
        assert trigger_after_reset.is_active is True

    # Recovery and Re-enabling Tests

    async def test_auto_disabled_trigger_manual_recovery(
        self, trigger_service, mock_task_service, mock_event_broker, sample_agent_id
    ):
        """Test manual recovery of auto-disabled trigger."""
        # Create trigger with low threshold
        trigger_data = TriggerCreate(
            name="Recovery Test Trigger",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            failure_threshold=2,  # Low threshold
            created_by="recovery_test",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        trigger_id = trigger.id

        # Cause failures to auto-disable
        mock_task_service.create_task_from_params.side_effect = Exception("Failure")

        for i in range(2):  # Reach threshold
            execution_data = {"execution_time": datetime.utcnow().isoformat()}
            await trigger_service.execute_trigger(trigger_id, execution_data)

        # Verify trigger was auto-disabled
        disabled_trigger = await trigger_service.get_trigger(trigger_id)
        assert disabled_trigger.is_active is False
        assert disabled_trigger.consecutive_failures == 2

        # Fix the underlying issue
        mock_task_service.create_task_from_params.side_effect = None
        mock_task = MagicMock()
        mock_task.id = uuid4()
        mock_task_service.create_task_from_params.return_value = mock_task

        # Reset failure count (simulating admin intervention)
        await trigger_service.reset_trigger_failure_count(trigger_id)

        # Re-enable trigger
        enable_result = await trigger_service.enable_trigger(trigger_id)
        assert enable_result is True

        # Verify trigger is active and failure count is reset
        recovered_trigger = await trigger_service.get_trigger(trigger_id)
        assert recovered_trigger.is_active is True
        assert recovered_trigger.consecutive_failures == 0

        # Test that trigger works normally after recovery
        execution_data = {"execution_time": datetime.utcnow().isoformat()}
        result = await trigger_service.execute_trigger(trigger_id, execution_data)
        assert result.status == ExecutionStatus.SUCCESS

    async def test_webhook_trigger_safety_mechanisms(
        self, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test safety mechanisms for webhook triggers."""
        # Create webhook trigger
        trigger_data = TriggerCreate(
            name="Webhook Safety Test",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_type=WebhookType.GENERIC,
            failure_threshold=3,
            created_by="webhook_safety_test",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        trigger_id = trigger.id
        webhook_id = trigger.webhook_id

        # Make task service fail
        mock_task_service.create_task_from_params.side_effect = Exception("Webhook failure")

        # Simulate multiple webhook requests causing failures
        for i in range(3):  # Reach threshold
            execution_data = {
                "execution_time": datetime.utcnow().isoformat(),
                "source": "webhook",
                "request": {
                    "method": "POST",
                    "body": {"attempt": i + 1},
                    "headers": {"Content-Type": "application/json"},
                },
            }
            result = await trigger_service.execute_trigger(trigger_id, execution_data)
            assert result.status == ExecutionStatus.FAILED

        # Verify webhook trigger was auto-disabled
        disabled_trigger = await trigger_service.get_trigger(trigger_id)
        assert disabled_trigger.is_active is False
        assert disabled_trigger.consecutive_failures == 3
        assert disabled_trigger.webhook_id == webhook_id  # Webhook ID preserved

        # Verify subsequent webhook requests to disabled trigger
        execution_data = {
            "execution_time": datetime.utcnow().isoformat(),
            "source": "webhook",
            "request": {"method": "POST", "body": {"test": "disabled"}},
        }

        # Execution should still be attempted but may fail due to disabled state
        result = await trigger_service.execute_trigger(trigger_id, execution_data)
        # Behavior depends on implementation - could skip or fail

    # Edge Cases and Error Handling

    async def test_safety_mechanisms_with_concurrent_executions(
        self, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test safety mechanisms under concurrent execution load."""
        # Create trigger
        trigger_data = TriggerCreate(
            name="Concurrent Safety Test",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            failure_threshold=5,
            created_by="concurrent_safety_test",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        trigger_id = trigger.id

        # Make task service fail
        mock_task_service.create_task_from_params.side_effect = Exception("Concurrent failure")

        # Execute trigger concurrently multiple times
        async def execute_trigger():
            execution_data = {"execution_time": datetime.utcnow().isoformat()}
            return await trigger_service.execute_trigger(trigger_id, execution_data)

        # Run 10 concurrent executions
        tasks = [execute_trigger() for _ in range(10)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify all executions completed (some may have failed)
        for result in results:
            assert not isinstance(result, Exception) or "Concurrent failure" in str(result)

        # Verify trigger state is consistent
        final_trigger = await trigger_service.get_trigger(trigger_id)
        assert final_trigger is not None
        # Consecutive failures should be reasonable (not more than actual executions)
        assert final_trigger.consecutive_failures <= 10

    async def test_safety_status_for_nonexistent_trigger(self, trigger_service):
        """Test safety status check for non-existent trigger."""
        fake_trigger_id = uuid4()

        safety_status = await trigger_service.get_trigger_safety_status(fake_trigger_id)
        assert safety_status is None

    async def test_failure_count_reset_for_nonexistent_trigger(self, trigger_service):
        """Test failure count reset for non-existent trigger."""
        fake_trigger_id = uuid4()

        result = await trigger_service.reset_trigger_failure_count(fake_trigger_id)
        assert result is False

    async def test_custom_failure_thresholds(
        self, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test triggers with custom failure thresholds."""
        # Create triggers with different thresholds
        thresholds = [1, 3, 10]
        triggers = []

        for threshold in thresholds:
            trigger_data = TriggerCreate(
                name=f"Custom Threshold {threshold} Trigger",
                agent_id=sample_agent_id,
                trigger_type=TriggerType.CRON,
                cron_expression="0 9 * * *",
                failure_threshold=threshold,
                created_by="custom_threshold_test",
            )
            trigger = await trigger_service.create_trigger(trigger_data)
            triggers.append((trigger, threshold))

        # Make task service fail
        mock_task_service.create_task_from_params.side_effect = Exception("Custom threshold test")

        # Execute each trigger up to its threshold
        for trigger, threshold in triggers:
            for i in range(threshold):
                execution_data = {"execution_time": datetime.utcnow().isoformat()}
                await trigger_service.execute_trigger(trigger.id, execution_data)

            # Verify trigger was auto-disabled at its specific threshold
            updated_trigger = await trigger_service.get_trigger(trigger.id)
            assert updated_trigger.is_active is False
            assert updated_trigger.consecutive_failures == threshold

    async def test_event_publishing_failure_handling(
        self, trigger_service, mock_task_service, mock_event_broker, sample_agent_id
    ):
        """Test that event publishing failures don't break safety mechanisms."""
        # Create trigger
        trigger_data = TriggerCreate(
            name="Event Failure Test",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            failure_threshold=2,
            created_by="event_failure_test",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        trigger_id = trigger.id

        # Make task service and event broker fail
        mock_task_service.create_task_from_params.side_effect = Exception("Task failure")
        mock_event_broker.publish.side_effect = Exception("Event broker failure")

        # Execute trigger to reach threshold
        for i in range(2):
            execution_data = {"execution_time": datetime.utcnow().isoformat()}
            # Should not raise exception despite event broker failure
            result = await trigger_service.execute_trigger(trigger_id, execution_data)
            assert result.status == ExecutionStatus.FAILED

        # Verify trigger was still auto-disabled despite event publishing failure
        disabled_trigger = await trigger_service.get_trigger(trigger_id)
        assert disabled_trigger.is_active is False
        assert disabled_trigger.consecutive_failures == 2

        # Verify event publishing was attempted
        assert mock_event_broker.publish.call_count > 0
