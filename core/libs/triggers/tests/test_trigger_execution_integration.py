"""Integration tests for trigger execution engine."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_triggers.domain.enums import ExecutionStatus
from agentarea_triggers.domain.models import CronTrigger, TriggerExecution
from agentarea_triggers.trigger_service import TriggerService

pytestmark = pytest.mark.asyncio


class TestTriggerExecutionIntegration:
    """Integration tests for trigger execution with TaskService."""

    @pytest.fixture
    def mock_repositories(self):
        """Create mock repositories."""
        trigger_repo = AsyncMock()
        execution_repo = AsyncMock()
        return trigger_repo, execution_repo

    @pytest.fixture
    def mock_task_service(self):
        """Create mock TaskService."""
        task_service = AsyncMock()

        # Mock task creation
        mock_task = MagicMock()
        mock_task.id = uuid4()
        task_service.create_task_from_params.return_value = mock_task

        return task_service

    @pytest.fixture
    def sample_trigger(self):
        """Create a sample trigger for testing."""
        return CronTrigger(
            id=uuid4(),
            name="Integration Test Trigger",
            description="Test trigger for integration tests",
            agent_id=uuid4(),
            cron_expression="0 9 * * 1-5",
            timezone="UTC",
            task_parameters={"integration_test": True},
            conditions={"hour_range": [9, 17]},
            created_by="integration_test",
            is_active=True,
        )

    async def test_complete_trigger_execution_flow(
        self, mock_repositories, mock_task_service, sample_trigger
    ):
        """Test the complete trigger execution flow from trigger to task creation."""
        trigger_repo, execution_repo = mock_repositories

        # Setup trigger repository
        trigger_repo.get.return_value = sample_trigger
        trigger_repo.update.return_value = sample_trigger

        # Setup execution repository
        mock_execution = TriggerExecution(
            trigger_id=sample_trigger.id,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=150,
            task_id=mock_task_service.create_task_from_params.return_value.id,
        )
        execution_repo.create.return_value = mock_execution

        # Create trigger service with mocked dependencies
        trigger_service = TriggerService(
            trigger_repository=trigger_repo,
            trigger_execution_repository=execution_repo,
            event_broker=AsyncMock(),
            agent_repository=None,
            task_service=mock_task_service,
            llm_condition_evaluator=None,
            temporal_schedule_manager=None,
        )

        # Execute trigger
        execution_data = {
            "execution_time": datetime.utcnow().isoformat(),
            "source": "cron",
            "schedule_info": {"next_run": "2024-01-02T09:00:00Z"},
        }

        result = await trigger_service.execute_trigger(sample_trigger.id, execution_data)

        # Verify execution was successful
        assert result.status == ExecutionStatus.SUCCESS
        assert result.task_id is not None
        assert result.execution_time_ms > 0

        # Verify task was created with correct parameters
        mock_task_service.create_task_from_params.assert_called_once()
        call_args = mock_task_service.create_task_from_params.call_args

        # Check task creation parameters
        assert call_args.kwargs["title"] == f"Trigger: {sample_trigger.name}"
        assert call_args.kwargs["user_id"] == sample_trigger.created_by
        assert call_args.kwargs["agent_id"] == sample_trigger.agent_id

        # Check task parameters include trigger metadata
        task_params = call_args.kwargs["task_parameters"]
        assert task_params["trigger_id"] == str(sample_trigger.id)
        assert task_params["trigger_type"] == "cron"
        assert task_params["trigger_name"] == sample_trigger.name
        assert task_params["integration_test"] is True  # From trigger's task_parameters
        assert task_params["trigger_data"] == execution_data

        # Verify execution was recorded
        execution_repo.create.assert_called_once()

    async def test_trigger_execution_with_condition_evaluation(
        self, mock_repositories, mock_task_service, sample_trigger
    ):
        """Test trigger execution with condition evaluation."""
        trigger_repo, execution_repo = mock_repositories

        # Setup trigger with specific conditions
        sample_trigger.conditions = {
            "field_matches": {"request.body.type": "test"},
            "time_conditions": {"hour_range": [9, 17]},
        }

        trigger_repo.get.return_value = sample_trigger
        trigger_repo.update.return_value = sample_trigger

        # Setup execution repository
        mock_execution = TriggerExecution(
            trigger_id=sample_trigger.id,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=100,
            task_id=mock_task_service.create_task_from_params.return_value.id,
        )
        execution_repo.create.return_value = mock_execution

        # Create trigger service
        trigger_service = TriggerService(
            trigger_repository=trigger_repo,
            trigger_execution_repository=execution_repo,
            event_broker=AsyncMock(),
            agent_repository=None,
            task_service=mock_task_service,
            llm_condition_evaluator=None,
            temporal_schedule_manager=None,
        )

        # Test with matching conditions
        execution_data = {
            "execution_time": "2024-01-01T10:00:00Z",  # 10 AM, within hour range
            "request": {
                "body": {
                    "type": "test"  # Matches field condition
                }
            },
        }

        # Mock datetime for time condition evaluation
        with patch("agentarea_triggers.trigger_service.datetime") as mock_datetime:
            mock_datetime.utcnow.return_value = datetime(2024, 1, 1, 10, 0, 0)  # 10 AM

            result = await trigger_service.execute_trigger(sample_trigger.id, execution_data)

        # Verify execution was successful
        assert result.status == ExecutionStatus.SUCCESS
        assert result.task_id is not None

        # Verify task was created
        mock_task_service.create_task_from_params.assert_called_once()

    async def test_trigger_execution_conditions_not_met(
        self, mock_repositories, mock_task_service, sample_trigger
    ):
        """Test trigger execution when conditions are not met."""
        trigger_repo, execution_repo = mock_repositories

        # Setup trigger with specific conditions
        sample_trigger.conditions = {"field_matches": {"request.body.type": "expected_type"}}

        trigger_repo.get.return_value = sample_trigger

        # Create trigger service
        trigger_service = TriggerService(
            trigger_repository=trigger_repo,
            trigger_execution_repository=execution_repo,
            event_broker=AsyncMock(),
            agent_repository=None,
            task_service=mock_task_service,
            llm_condition_evaluator=None,
            temporal_schedule_manager=None,
        )

        # Test with non-matching conditions
        execution_data = {
            "execution_time": datetime.utcnow().isoformat(),
            "request": {
                "body": {
                    "type": "different_type"  # Doesn't match condition
                }
            },
        }

        # Evaluate conditions directly (this should return False)
        conditions_met = await trigger_service.evaluate_trigger_conditions(
            sample_trigger, execution_data
        )

        # Verify conditions are not met
        assert conditions_met is False

    async def test_webhook_trigger_parameter_building(self, mock_repositories, mock_task_service):
        """Test parameter building for webhook triggers."""
        from agentarea_triggers.domain.models import WebhookTrigger

        trigger_repo, execution_repo = mock_repositories

        # Create webhook trigger
        webhook_trigger = WebhookTrigger(
            id=uuid4(),
            name="Webhook Test Trigger",
            description="Test webhook trigger",
            agent_id=uuid4(),
            webhook_id="test_webhook_123",
            allowed_methods=["POST"],
            task_parameters={"webhook_param": "webhook_value"},
            created_by="webhook_test",
            is_active=True,
        )

        trigger_repo.get.return_value = webhook_trigger

        # Create trigger service
        trigger_service = TriggerService(
            trigger_repository=trigger_repo,
            trigger_execution_repository=execution_repo,
            event_broker=AsyncMock(),
            agent_repository=None,
            task_service=mock_task_service,
            llm_condition_evaluator=None,
            temporal_schedule_manager=None,
        )

        # Test webhook execution data
        execution_data = {
            "execution_time": datetime.utcnow().isoformat(),
            "source": "webhook",
            "request": {
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "body": {"message": "Hello from webhook"},
                "query_params": {"source": "external"},
            },
        }

        # Build task parameters
        params = await trigger_service._build_task_parameters(webhook_trigger, execution_data)

        # Verify webhook-specific parameters
        assert params["trigger_id"] == str(webhook_trigger.id)
        assert params["trigger_type"] == "webhook"
        assert params["trigger_name"] == webhook_trigger.name
        assert params["webhook_param"] == "webhook_value"  # From trigger's task_parameters
        assert params["trigger_data"] == execution_data
        assert "execution_time" in params

        # Verify webhook request data is preserved
        assert params["trigger_data"]["request"]["method"] == "POST"
        assert params["trigger_data"]["request"]["body"]["message"] == "Hello from webhook"

    async def test_error_handling_in_execution_flow(
        self, mock_repositories, mock_task_service, sample_trigger
    ):
        """Test error handling during trigger execution."""
        trigger_repo, execution_repo = mock_repositories

        # Setup trigger repository
        trigger_repo.get.return_value = sample_trigger
        trigger_repo.update.return_value = sample_trigger

        # Make task service fail
        mock_task_service.create_task_from_params.side_effect = Exception("Task creation failed")

        # Setup execution repository for failure recording
        mock_execution = TriggerExecution(
            trigger_id=sample_trigger.id,
            status=ExecutionStatus.FAILED,
            execution_time_ms=50,
            error_message="Task creation failed",
        )
        execution_repo.create.return_value = mock_execution

        # Create trigger service
        trigger_service = TriggerService(
            trigger_repository=trigger_repo,
            trigger_execution_repository=execution_repo,
            event_broker=AsyncMock(),
            agent_repository=None,
            task_service=mock_task_service,
            llm_condition_evaluator=None,
            temporal_schedule_manager=None,
        )

        # Execute trigger
        execution_data = {"execution_time": datetime.utcnow().isoformat()}

        result = await trigger_service.execute_trigger(sample_trigger.id, execution_data)

        # Verify execution failed but was handled gracefully
        assert result.status == ExecutionStatus.FAILED
        assert "Task creation failed" in result.error_message

        # Verify failure was recorded
        execution_repo.create.assert_called_once()
