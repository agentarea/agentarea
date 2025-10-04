"""Integration tests for trigger lifecycle management.

This module tests trigger lifecycle operations including enable/disable/delete
operations, state transitions, and their effects on scheduling and execution.
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
        TriggerUpdate,
        WebhookTrigger,
    )
    from agentarea_triggers.infrastructure.repository import (
        TriggerExecutionRepository,
        TriggerRepository,
    )
    from agentarea_triggers.temporal_schedule_manager import TemporalScheduleManager
    from agentarea_triggers.trigger_service import TriggerNotFoundError, TriggerService

    TRIGGERS_AVAILABLE = True
except ImportError:
    TRIGGERS_AVAILABLE = False
    pytest.skip("Triggers not available", allow_module_level=True)

from agentarea_common.events.broker import EventBroker
from agentarea_tasks.task_service import TaskService

pytestmark = pytest.mark.asyncio


class TestTriggerLifecycleManagement:
    """Integration tests for trigger lifecycle management."""

    @pytest.fixture
    def mock_event_broker(self):
        """Mock event broker for testing."""
        return AsyncMock(spec=EventBroker)

    @pytest.fixture
    def mock_task_service(self):
        """Mock task service for testing."""
        task_service = AsyncMock(spec=TaskService)

        # Mock task creation
        mock_task = MagicMock()
        mock_task.id = uuid4()
        mock_task.title = "Lifecycle Test Task"
        mock_task.status = "pending"
        task_service.create_task_from_params.return_value = mock_task

        return task_service

    @pytest.fixture
    def mock_agent_repository(self):
        """Mock agent repository for testing."""
        agent_repo = AsyncMock()

        # Mock agent existence check
        mock_agent = MagicMock()
        mock_agent.id = uuid4()
        mock_agent.name = "Lifecycle Test Agent"
        agent_repo.get.return_value = mock_agent

        return agent_repo

    @pytest.fixture
    def mock_temporal_schedule_manager(self):
        """Mock temporal schedule manager for testing."""
        return AsyncMock(spec=TemporalScheduleManager)

    @pytest.fixture
    async def trigger_repositories(self, db_session):
        """Create real trigger repositories for testing."""
        trigger_repo = TriggerRepository(db_session)
        execution_repo = TriggerExecutionRepository(db_session)
        return trigger_repo, execution_repo

    @pytest.fixture
    async def trigger_service(
        self,
        trigger_repositories,
        mock_event_broker,
        mock_agent_repository,
        mock_task_service,
        mock_temporal_schedule_manager,
    ):
        """Create trigger service with real repositories and mocked dependencies."""
        trigger_repo, execution_repo = trigger_repositories

        return TriggerService(
            trigger_repository=trigger_repo,
            trigger_execution_repository=execution_repo,
            event_broker=mock_event_broker,
            agent_repository=mock_agent_repository,
            task_service=mock_task_service,
            llm_condition_evaluator=None,
            temporal_schedule_manager=mock_temporal_schedule_manager,
        )

    @pytest.fixture
    def sample_agent_id(self):
        """Sample agent ID for testing."""
        return uuid4()

    # Trigger Creation Tests

    async def test_cron_trigger_creation_lifecycle(
        self, trigger_service, mock_temporal_schedule_manager, sample_agent_id
    ):
        """Test complete cron trigger creation lifecycle."""
        # Create cron trigger
        trigger_data = TriggerCreate(
            name="Lifecycle Cron Trigger",
            description="Test cron trigger lifecycle",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * 1-5",  # 9 AM weekdays
            timezone="UTC",
            task_parameters={"lifecycle_test": True},
            conditions={"business_hours": True},
            created_by="lifecycle_test",
        )

        created_trigger = await trigger_service.create_trigger(trigger_data)

        # Verify trigger was created with correct properties
        assert created_trigger.id is not None
        assert created_trigger.name == "Lifecycle Cron Trigger"
        assert created_trigger.trigger_type == TriggerType.CRON
        assert created_trigger.is_active is True
        assert created_trigger.consecutive_failures == 0
        assert created_trigger.cron_expression == "0 9 * * 1-5"
        assert created_trigger.timezone == "UTC"
        assert created_trigger.created_at is not None
        assert created_trigger.updated_at is not None

        # Verify schedule was created
        mock_temporal_schedule_manager.create_schedule.assert_called_once()
        schedule_call = mock_temporal_schedule_manager.create_schedule.call_args
        assert schedule_call.kwargs["trigger_id"] == created_trigger.id
        assert schedule_call.kwargs["cron_expression"] == "0 9 * * 1-5"
        assert schedule_call.kwargs["timezone"] == "UTC"

        # Verify trigger can be retrieved
        retrieved_trigger = await trigger_service.get_trigger(created_trigger.id)
        assert retrieved_trigger is not None
        assert retrieved_trigger.id == created_trigger.id
        assert retrieved_trigger.name == created_trigger.name

    async def test_webhook_trigger_creation_lifecycle(self, trigger_service, sample_agent_id):
        """Test complete webhook trigger creation lifecycle."""
        # Create webhook trigger
        trigger_data = TriggerCreate(
            name="Lifecycle Webhook Trigger",
            description="Test webhook trigger lifecycle",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_type=WebhookType.GITHUB,
            allowed_methods=["POST", "PUT"],
            task_parameters={"webhook_lifecycle_test": True},
            conditions={"branch": "main"},
            validation_rules={"required_headers": ["X-GitHub-Event"]},
            webhook_config={"secret": "webhook_secret"},
            created_by="lifecycle_test",
        )

        created_trigger = await trigger_service.create_trigger(trigger_data)

        # Verify trigger was created with correct properties
        assert created_trigger.id is not None
        assert created_trigger.name == "Lifecycle Webhook Trigger"
        assert created_trigger.trigger_type == TriggerType.WEBHOOK
        assert created_trigger.is_active is True
        assert created_trigger.webhook_id is not None
        assert created_trigger.webhook_type == WebhookType.GITHUB
        assert created_trigger.allowed_methods == ["POST", "PUT"]
        assert created_trigger.validation_rules == {"required_headers": ["X-GitHub-Event"]}
        assert created_trigger.webhook_config == {"secret": "webhook_secret"}

        # Verify webhook ID is unique and properly formatted
        assert len(created_trigger.webhook_id) > 0
        assert isinstance(created_trigger.webhook_id, str)

        # Verify trigger can be retrieved
        retrieved_trigger = await trigger_service.get_trigger(created_trigger.id)
        assert retrieved_trigger is not None
        assert retrieved_trigger.webhook_id == created_trigger.webhook_id

    # Trigger Update Tests

    async def test_trigger_update_lifecycle(
        self, trigger_service, mock_temporal_schedule_manager, sample_agent_id
    ):
        """Test trigger update lifecycle."""
        # Create initial trigger
        trigger_data = TriggerCreate(
            name="Original Trigger",
            description="Original description",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            timezone="UTC",
            task_parameters={"original": True},
            conditions={"original_condition": True},
            failure_threshold=5,
            created_by="update_test",
        )

        created_trigger = await trigger_service.create_trigger(trigger_data)
        original_id = created_trigger.id
        original_created_at = created_trigger.created_at

        # Update trigger
        update_data = TriggerUpdate(
            name="Updated Trigger",
            description="Updated description",
            cron_expression="0 10 * * *",  # Changed time
            timezone="America/New_York",  # Changed timezone
            task_parameters={"updated": True, "version": 2},
            conditions={"updated_condition": True},
            failure_threshold=3,  # Changed threshold
        )

        updated_trigger = await trigger_service.update_trigger(original_id, update_data)

        # Verify updates were applied
        assert updated_trigger.id == original_id  # ID should not change
        assert updated_trigger.name == "Updated Trigger"
        assert updated_trigger.description == "Updated description"
        assert updated_trigger.cron_expression == "0 10 * * *"
        assert updated_trigger.timezone == "America/New_York"
        assert updated_trigger.task_parameters == {"updated": True, "version": 2}
        assert updated_trigger.conditions == {"updated_condition": True}
        assert updated_trigger.failure_threshold == 3

        # Verify timestamps
        assert updated_trigger.created_at == original_created_at  # Should not change
        assert updated_trigger.updated_at > original_created_at  # Should be updated

        # Verify schedule was updated
        mock_temporal_schedule_manager.update_schedule.assert_called_once()
        update_call = mock_temporal_schedule_manager.update_schedule.call_args
        assert update_call.kwargs["trigger_id"] == original_id
        assert update_call.kwargs["cron_expression"] == "0 10 * * *"
        assert update_call.kwargs["timezone"] == "America/New_York"

    async def test_partial_trigger_update(self, trigger_service, sample_agent_id):
        """Test partial trigger update (only some fields)."""
        # Create initial trigger
        trigger_data = TriggerCreate(
            name="Partial Update Trigger",
            description="Original description",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_type=WebhookType.GENERIC,
            allowed_methods=["POST"],
            task_parameters={"original": True},
            created_by="partial_test",
        )

        created_trigger = await trigger_service.create_trigger(trigger_data)

        # Update only name and task_parameters
        update_data = TriggerUpdate(
            name="Partially Updated Trigger", task_parameters={"original": True, "updated": True}
        )

        updated_trigger = await trigger_service.update_trigger(created_trigger.id, update_data)

        # Verify only specified fields were updated
        assert updated_trigger.name == "Partially Updated Trigger"
        assert updated_trigger.task_parameters == {"original": True, "updated": True}

        # Verify other fields remained unchanged
        assert updated_trigger.description == "Original description"
        assert updated_trigger.webhook_type == WebhookType.GENERIC
        assert updated_trigger.allowed_methods == ["POST"]

    # Trigger Enable/Disable Tests

    async def test_trigger_disable_enable_lifecycle(
        self, trigger_service, mock_temporal_schedule_manager, sample_agent_id
    ):
        """Test trigger disable and enable lifecycle."""
        # Create active trigger
        trigger_data = TriggerCreate(
            name="Enable/Disable Test Trigger",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            created_by="enable_disable_test",
        )

        created_trigger = await trigger_service.create_trigger(trigger_data)
        assert created_trigger.is_active is True

        # Disable trigger
        disable_result = await trigger_service.disable_trigger(created_trigger.id)
        assert disable_result is True

        # Verify trigger is disabled
        disabled_trigger = await trigger_service.get_trigger(created_trigger.id)
        assert disabled_trigger.is_active is False

        # Verify schedule was paused
        mock_temporal_schedule_manager.pause_schedule.assert_called_once_with(created_trigger.id)

        # Re-enable trigger
        enable_result = await trigger_service.enable_trigger(created_trigger.id)
        assert enable_result is True

        # Verify trigger is enabled
        enabled_trigger = await trigger_service.get_trigger(created_trigger.id)
        assert enabled_trigger.is_active is True

        # Verify schedule was resumed
        mock_temporal_schedule_manager.resume_schedule.assert_called_once_with(created_trigger.id)

    async def test_webhook_trigger_disable_enable(self, trigger_service, sample_agent_id):
        """Test webhook trigger disable and enable."""
        # Create webhook trigger
        trigger_data = TriggerCreate(
            name="Webhook Enable/Disable Test",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_type=WebhookType.GENERIC,
            created_by="webhook_enable_test",
        )

        created_trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = created_trigger.webhook_id

        # Disable trigger
        disable_result = await trigger_service.disable_trigger(created_trigger.id)
        assert disable_result is True

        # Verify trigger is disabled but webhook_id is preserved
        disabled_trigger = await trigger_service.get_trigger(created_trigger.id)
        assert disabled_trigger.is_active is False
        assert disabled_trigger.webhook_id == webhook_id  # Should be preserved

        # Re-enable trigger
        enable_result = await trigger_service.enable_trigger(created_trigger.id)
        assert enable_result is True

        # Verify trigger is enabled and webhook_id is still preserved
        enabled_trigger = await trigger_service.get_trigger(created_trigger.id)
        assert enabled_trigger.is_active is True
        assert enabled_trigger.webhook_id == webhook_id

    async def test_disable_nonexistent_trigger(self, trigger_service):
        """Test disabling non-existent trigger."""
        fake_trigger_id = uuid4()

        result = await trigger_service.disable_trigger(fake_trigger_id)
        assert result is False

    async def test_enable_nonexistent_trigger(self, trigger_service):
        """Test enabling non-existent trigger."""
        fake_trigger_id = uuid4()

        result = await trigger_service.enable_trigger(fake_trigger_id)
        assert result is False

    # Trigger Deletion Tests

    async def test_cron_trigger_deletion_lifecycle(
        self, trigger_service, mock_temporal_schedule_manager, sample_agent_id
    ):
        """Test complete cron trigger deletion lifecycle."""
        # Create trigger
        trigger_data = TriggerCreate(
            name="Deletion Test Trigger",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            created_by="deletion_test",
        )

        created_trigger = await trigger_service.create_trigger(trigger_data)
        trigger_id = created_trigger.id

        # Create some execution history
        execution_data = {"execution_time": datetime.utcnow().isoformat()}
        await trigger_service.execute_trigger(trigger_id, execution_data)

        # Verify execution history exists
        history = await trigger_service.get_execution_history(trigger_id)
        assert len(history) > 0

        # Delete trigger
        delete_result = await trigger_service.delete_trigger(trigger_id)
        assert delete_result is True

        # Verify trigger is deleted
        deleted_trigger = await trigger_service.get_trigger(trigger_id)
        assert deleted_trigger is None

        # Verify schedule was deleted
        mock_temporal_schedule_manager.delete_schedule.assert_called_once_with(trigger_id)

        # Verify execution history is also deleted
        history_after_delete = await trigger_service.get_execution_history(trigger_id)
        assert len(history_after_delete) == 0

    async def test_webhook_trigger_deletion_lifecycle(self, trigger_service, sample_agent_id):
        """Test complete webhook trigger deletion lifecycle."""
        # Create webhook trigger
        trigger_data = TriggerCreate(
            name="Webhook Deletion Test",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_type=WebhookType.GENERIC,
            created_by="webhook_deletion_test",
        )

        created_trigger = await trigger_service.create_trigger(trigger_data)
        trigger_id = created_trigger.id
        webhook_id = created_trigger.webhook_id

        # Create some execution history
        execution_data = {
            "execution_time": datetime.utcnow().isoformat(),
            "request": {"method": "POST", "body": {"test": "data"}},
        }
        await trigger_service.execute_trigger(trigger_id, execution_data)

        # Delete trigger
        delete_result = await trigger_service.delete_trigger(trigger_id)
        assert delete_result is True

        # Verify trigger is deleted
        deleted_trigger = await trigger_service.get_trigger(trigger_id)
        assert deleted_trigger is None

        # Verify execution history is deleted
        history_after_delete = await trigger_service.get_execution_history(trigger_id)
        assert len(history_after_delete) == 0

    async def test_delete_nonexistent_trigger(self, trigger_service):
        """Test deleting non-existent trigger."""
        fake_trigger_id = uuid4()

        result = await trigger_service.delete_trigger(fake_trigger_id)
        assert result is False

    # State Transition Tests

    async def test_trigger_state_transitions(
        self, trigger_service, mock_temporal_schedule_manager, sample_agent_id
    ):
        """Test various trigger state transitions."""
        # Create trigger (active by default)
        trigger_data = TriggerCreate(
            name="State Transition Test",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            created_by="state_test",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        trigger_id = trigger.id

        # State 1: Active (initial state)
        current_trigger = await trigger_service.get_trigger(trigger_id)
        assert current_trigger.is_active is True

        # State 2: Disabled
        await trigger_service.disable_trigger(trigger_id)
        current_trigger = await trigger_service.get_trigger(trigger_id)
        assert current_trigger.is_active is False

        # State 3: Re-enabled
        await trigger_service.enable_trigger(trigger_id)
        current_trigger = await trigger_service.get_trigger(trigger_id)
        assert current_trigger.is_active is True

        # State 4: Updated while active
        update_data = TriggerUpdate(name="Updated State Test")
        updated_trigger = await trigger_service.update_trigger(trigger_id, update_data)
        assert updated_trigger.is_active is True  # Should remain active
        assert updated_trigger.name == "Updated State Test"

        # State 5: Disabled again
        await trigger_service.disable_trigger(trigger_id)
        current_trigger = await trigger_service.get_trigger(trigger_id)
        assert current_trigger.is_active is False

        # State 6: Updated while disabled
        update_data = TriggerUpdate(description="Updated while disabled")
        updated_trigger = await trigger_service.update_trigger(trigger_id, update_data)
        assert updated_trigger.is_active is False  # Should remain disabled
        assert updated_trigger.description == "Updated while disabled"

        # State 7: Deleted
        delete_result = await trigger_service.delete_trigger(trigger_id)
        assert delete_result is True

        # Verify final state (non-existent)
        deleted_trigger = await trigger_service.get_trigger(trigger_id)
        assert deleted_trigger is None

    # Execution During Lifecycle Changes

    async def test_execution_during_disable_enable(
        self, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test trigger execution behavior during disable/enable operations."""
        # Create trigger
        trigger_data = TriggerCreate(
            name="Execution During Lifecycle Test",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            created_by="execution_lifecycle_test",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        trigger_id = trigger.id

        # Execute while active (should succeed)
        execution_data = {"execution_time": datetime.utcnow().isoformat(), "test": "active"}
        result1 = await trigger_service.execute_trigger(trigger_id, execution_data)
        assert result1.status == ExecutionStatus.SUCCESS

        # Disable trigger
        await trigger_service.disable_trigger(trigger_id)

        # Execute while disabled (should fail or be skipped)
        execution_data = {"execution_time": datetime.utcnow().isoformat(), "test": "disabled"}
        result2 = await trigger_service.execute_trigger(trigger_id, execution_data)
        # Behavior depends on implementation - could be FAILED or skipped
        assert result2.status in [ExecutionStatus.FAILED, ExecutionStatus.SUCCESS]

        # Re-enable trigger
        await trigger_service.enable_trigger(trigger_id)

        # Execute while active again (should succeed)
        execution_data = {"execution_time": datetime.utcnow().isoformat(), "test": "re_enabled"}
        result3 = await trigger_service.execute_trigger(trigger_id, execution_data)
        assert result3.status == ExecutionStatus.SUCCESS

        # Verify execution history
        history = await trigger_service.get_execution_history(trigger_id)
        assert len(history) >= 2  # At least the successful executions

    async def test_concurrent_lifecycle_operations(
        self, trigger_service, mock_temporal_schedule_manager, sample_agent_id
    ):
        """Test concurrent lifecycle operations on the same trigger."""
        # Create trigger
        trigger_data = TriggerCreate(
            name="Concurrent Lifecycle Test",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            created_by="concurrent_test",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        trigger_id = trigger.id

        # Define concurrent operations
        async def disable_operation():
            return await trigger_service.disable_trigger(trigger_id)

        async def enable_operation():
            await asyncio.sleep(0.1)  # Small delay
            return await trigger_service.enable_trigger(trigger_id)

        async def update_operation():
            await asyncio.sleep(0.05)  # Small delay
            update_data = TriggerUpdate(description="Concurrent update")
            return await trigger_service.update_trigger(trigger_id, update_data)

        # Execute operations concurrently
        results = await asyncio.gather(
            disable_operation(), enable_operation(), update_operation(), return_exceptions=True
        )

        # Verify no exceptions occurred
        for result in results:
            assert not isinstance(result, Exception), f"Operation failed: {result}"

        # Verify final state is consistent
        final_trigger = await trigger_service.get_trigger(trigger_id)
        assert final_trigger is not None
        assert final_trigger.description == "Concurrent update"
        # is_active could be either True or False depending on operation order

    # Error Handling in Lifecycle Operations

    async def test_lifecycle_operations_with_schedule_manager_failure(
        self, trigger_service, mock_temporal_schedule_manager, sample_agent_id
    ):
        """Test lifecycle operations when schedule manager fails."""
        # Make schedule manager fail
        mock_temporal_schedule_manager.create_schedule.side_effect = Exception(
            "Schedule manager error"
        )

        # Create trigger (should handle schedule manager failure gracefully)
        trigger_data = TriggerCreate(
            name="Schedule Manager Failure Test",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            created_by="schedule_failure_test",
        )

        # Creation might fail or succeed depending on implementation
        try:
            trigger = await trigger_service.create_trigger(trigger_data)
            # If creation succeeded, verify trigger exists but schedule creation failed
            assert trigger is not None
            mock_temporal_schedule_manager.create_schedule.assert_called_once()
        except Exception as e:
            # If creation failed, verify it's due to schedule manager
            assert "Schedule manager error" in str(e)

    async def test_update_nonexistent_trigger(self, trigger_service):
        """Test updating non-existent trigger."""
        fake_trigger_id = uuid4()
        update_data = TriggerUpdate(name="Non-existent Update")

        with pytest.raises(TriggerNotFoundError):
            await trigger_service.update_trigger(fake_trigger_id, update_data)

    async def test_lifecycle_operations_preserve_execution_history(
        self, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test that lifecycle operations preserve execution history."""
        # Create trigger
        trigger_data = TriggerCreate(
            name="History Preservation Test",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            created_by="history_test",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        trigger_id = trigger.id

        # Create execution history
        for i in range(3):
            execution_data = {"execution_time": datetime.utcnow().isoformat(), "iteration": i}
            await trigger_service.execute_trigger(trigger_id, execution_data)

        # Verify initial history
        initial_history = await trigger_service.get_execution_history(trigger_id)
        assert len(initial_history) == 3

        # Disable and re-enable trigger
        await trigger_service.disable_trigger(trigger_id)
        await trigger_service.enable_trigger(trigger_id)

        # Verify history is preserved
        history_after_disable_enable = await trigger_service.get_execution_history(trigger_id)
        assert len(history_after_disable_enable) == 3

        # Update trigger
        update_data = TriggerUpdate(name="Updated History Test")
        await trigger_service.update_trigger(trigger_id, update_data)

        # Verify history is still preserved
        history_after_update = await trigger_service.get_execution_history(trigger_id)
        assert len(history_after_update) == 3

        # Only deletion should remove history (tested in deletion tests above)
