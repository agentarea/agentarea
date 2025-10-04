"""Unit tests for trigger execution engine."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_triggers.domain.enums import ExecutionStatus
from agentarea_triggers.domain.models import CronTrigger, TriggerExecution, WebhookTrigger
from agentarea_triggers.trigger_service import TriggerNotFoundError, TriggerService

pytestmark = pytest.mark.asyncio


class TestTriggerExecutionEngine:
    """Test cases for trigger execution engine."""

    @pytest.fixture
    def mock_repositories(self):
        """Create mock repositories."""
        trigger_repo = AsyncMock()
        execution_repo = AsyncMock()
        return trigger_repo, execution_repo

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies."""
        event_broker = AsyncMock()
        agent_repository = AsyncMock()
        task_service = AsyncMock()
        llm_service = AsyncMock()
        temporal_schedule_manager = AsyncMock()

        return {
            "event_broker": event_broker,
            "agent_repository": agent_repository,
            "task_service": task_service,
            "llm_condition_evaluator": llm_service,
            "temporal_schedule_manager": temporal_schedule_manager,
        }

    @pytest.fixture
    def trigger_service(self, mock_repositories, mock_dependencies):
        """Create TriggerService with mocked dependencies."""
        trigger_repo, execution_repo = mock_repositories

        return TriggerService(
            trigger_repository=trigger_repo,
            trigger_execution_repository=execution_repo,
            **mock_dependencies,
        )

    @pytest.fixture
    def sample_cron_trigger(self):
        """Create a sample cron trigger."""
        return CronTrigger(
            id=uuid4(),
            name="Test Cron Trigger",
            description="Test cron trigger for unit tests",
            agent_id=uuid4(),
            cron_expression="0 9 * * 1-5",
            timezone="UTC",
            task_parameters={"test_param": "test_value"},
            conditions={"hour_range": [9, 17]},
            created_by="test_user",
            is_active=True,
        )

    @pytest.fixture
    def sample_webhook_trigger(self):
        """Create a sample webhook trigger."""
        return WebhookTrigger(
            id=uuid4(),
            name="Test Webhook Trigger",
            description="Test webhook trigger for unit tests",
            agent_id=uuid4(),
            webhook_id="test_webhook_123",
            allowed_methods=["POST"],
            task_parameters={"webhook_param": "webhook_value"},
            conditions={"field_matches": {"request.body.type": "test"}},
            created_by="test_user",
            is_active=True,
        )

    async def test_execute_trigger_success(
        self, trigger_service, sample_cron_trigger, mock_repositories
    ):
        """Test successful trigger execution."""
        trigger_repo, execution_repo = mock_repositories

        # Setup mocks
        trigger_repo.get.return_value = sample_cron_trigger
        trigger_repo.update.return_value = sample_cron_trigger

        # Mock task creation
        mock_task = MagicMock()
        mock_task.id = uuid4()
        trigger_service.task_service.create_task_from_params.return_value = mock_task

        # Mock execution recording
        mock_execution = TriggerExecution(
            trigger_id=sample_cron_trigger.id,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=100,
            task_id=mock_task.id,
        )
        execution_repo.create.return_value = mock_execution

        # Execute trigger
        execution_data = {"execution_time": datetime.utcnow().isoformat()}
        result = await trigger_service.execute_trigger(sample_cron_trigger.id, execution_data)

        # Verify results
        assert result.status == ExecutionStatus.SUCCESS
        assert result.task_id == mock_task.id
        assert result.execution_time_ms > 0

        # Verify task was created
        trigger_service.task_service.create_task_from_params.assert_called_once()

        # Verify execution was recorded
        execution_repo.create.assert_called_once()

    async def test_execute_trigger_not_found(self, trigger_service, mock_repositories):
        """Test trigger execution when trigger doesn't exist."""
        trigger_repo, _ = mock_repositories
        trigger_repo.get.return_value = None

        trigger_id = uuid4()
        execution_data = {"execution_time": datetime.utcnow().isoformat()}

        with pytest.raises(TriggerNotFoundError):
            await trigger_service.execute_trigger(trigger_id, execution_data)

    async def test_execute_trigger_inactive(
        self, trigger_service, sample_cron_trigger, mock_repositories
    ):
        """Test trigger execution when trigger is inactive."""
        trigger_repo, execution_repo = mock_repositories

        # Make trigger inactive
        sample_cron_trigger.is_active = False
        trigger_repo.get.return_value = sample_cron_trigger

        # Mock execution recording
        mock_execution = TriggerExecution(
            trigger_id=sample_cron_trigger.id,
            status=ExecutionStatus.FAILED,
            execution_time_ms=0,
            error_message="Trigger is inactive",
        )
        execution_repo.create.return_value = mock_execution

        # Execute trigger
        execution_data = {"execution_time": datetime.utcnow().isoformat()}
        result = await trigger_service.execute_trigger(sample_cron_trigger.id, execution_data)

        # Verify results
        assert result.status == ExecutionStatus.FAILED
        assert result.error_message == "Trigger is inactive"

        # Verify task was not created
        trigger_service.task_service.create_task_from_params.assert_not_called()

    # Rate limiting test removed - rate limiting moved to infrastructure layer

    async def test_execute_trigger_task_creation_failure(
        self, trigger_service, sample_cron_trigger, mock_repositories
    ):
        """Test trigger execution when task creation fails."""
        trigger_repo, execution_repo = mock_repositories

        # Setup mocks
        trigger_repo.get.return_value = sample_cron_trigger
        trigger_repo.update.return_value = sample_cron_trigger

        # Mock task creation failure
        trigger_service.task_service.create_task_from_params.side_effect = Exception(
            "Task creation failed"
        )

        # Mock execution recording
        mock_execution = TriggerExecution(
            trigger_id=sample_cron_trigger.id,
            status=ExecutionStatus.FAILED,
            execution_time_ms=100,
            error_message="Task creation failed",
        )
        execution_repo.create.return_value = mock_execution

        # Execute trigger
        execution_data = {"execution_time": datetime.utcnow().isoformat()}
        result = await trigger_service.execute_trigger(sample_cron_trigger.id, execution_data)

        # Verify results
        assert result.status == ExecutionStatus.FAILED
        assert "Task creation failed" in result.error_message

    async def test_build_task_parameters(self, trigger_service, sample_cron_trigger):
        """Test building task parameters from trigger and execution data."""
        execution_data = {
            "execution_time": "2024-01-01T09:00:00Z",
            "source": "cron",
            "custom_data": "test_value",
        }

        params = await trigger_service._build_task_parameters(sample_cron_trigger, execution_data)

        # Verify parameters
        assert params["trigger_id"] == str(sample_cron_trigger.id)
        assert params["trigger_type"] == "cron"  # Enum value is lowercase
        assert params["trigger_name"] == sample_cron_trigger.name
        assert params["test_param"] == "test_value"  # From trigger's task_parameters
        assert params["trigger_data"] == execution_data
        assert "execution_time" in params

    async def test_evaluate_trigger_conditions_no_conditions(
        self, trigger_service, sample_cron_trigger
    ):
        """Test condition evaluation when no conditions are set."""
        sample_cron_trigger.conditions = {}

        result = await trigger_service.evaluate_trigger_conditions(sample_cron_trigger, {})

        assert result is True

    async def test_evaluate_trigger_conditions_field_matches(
        self, trigger_service, sample_webhook_trigger
    ):
        """Test condition evaluation with field matching."""
        event_data = {"request": {"body": {"type": "test", "message": "Hello world"}}}

        result = await trigger_service.evaluate_trigger_conditions(
            sample_webhook_trigger, event_data
        )

        assert result is True

    async def test_evaluate_trigger_conditions_field_mismatch(
        self, trigger_service, sample_webhook_trigger
    ):
        """Test condition evaluation with field mismatch."""
        event_data = {"request": {"body": {"type": "other", "message": "Hello world"}}}

        result = await trigger_service.evaluate_trigger_conditions(
            sample_webhook_trigger, event_data
        )

        assert result is False

    async def test_evaluate_trigger_conditions_time_based(
        self, trigger_service, sample_cron_trigger
    ):
        """Test condition evaluation with time-based conditions."""
        # Test during business hours
        with patch("agentarea_triggers.trigger_service.datetime") as mock_datetime:
            mock_datetime.utcnow.return_value = datetime(2024, 1, 1, 10, 0, 0)  # 10 AM

            result = await trigger_service.evaluate_trigger_conditions(sample_cron_trigger, {})
            assert result is True

        # Test outside business hours
        with patch("agentarea_triggers.trigger_service.datetime") as mock_datetime:
            mock_datetime.utcnow.return_value = datetime(2024, 1, 1, 20, 0, 0)  # 8 PM

            result = await trigger_service.evaluate_trigger_conditions(sample_cron_trigger, {})
            assert result is False

    async def test_evaluate_trigger_conditions_weekdays_only(
        self, trigger_service, sample_cron_trigger
    ):
        """Test condition evaluation with weekdays only condition."""
        sample_cron_trigger.conditions = {"time_conditions": {"weekdays_only": True}}

        # Test on weekday (Monday = 0)
        with patch("agentarea_triggers.trigger_service.datetime") as mock_datetime:
            mock_datetime.utcnow.return_value = datetime(2024, 1, 1, 10, 0, 0)  # Monday

            result = await trigger_service.evaluate_trigger_conditions(sample_cron_trigger, {})
            assert result is True

        # Test on weekend (Saturday = 5)
        with patch("agentarea_triggers.trigger_service.datetime") as mock_datetime:
            mock_datetime.utcnow.return_value = datetime(2024, 1, 6, 10, 0, 0)  # Saturday

            result = await trigger_service.evaluate_trigger_conditions(sample_cron_trigger, {})
            assert result is False

    async def test_get_nested_value(self, trigger_service):
        """Test getting nested values from dictionary."""
        data = {"level1": {"level2": {"level3": "target_value"}}, "simple": "simple_value"}

        # Test nested access
        result = trigger_service._get_nested_value(data, "level1.level2.level3")
        assert result == "target_value"

        # Test simple access
        result = trigger_service._get_nested_value(data, "simple")
        assert result == "simple_value"

        # Test non-existent path
        result = trigger_service._get_nested_value(data, "nonexistent.path")
        assert result is None

    async def test_record_execution_success(
        self, trigger_service, sample_cron_trigger, mock_repositories
    ):
        """Test recording successful execution."""
        _, execution_repo = mock_repositories

        mock_execution = TriggerExecution(
            trigger_id=sample_cron_trigger.id,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=150,
            task_id=uuid4(),
        )
        execution_repo.create.return_value = mock_execution

        result = await trigger_service._record_execution_success(
            sample_cron_trigger.id, 150, mock_execution.task_id, {"test": "data"}
        )

        assert result.status == ExecutionStatus.SUCCESS
        assert result.execution_time_ms == 150
        assert result.task_id == mock_execution.task_id

    async def test_record_execution_failure(
        self, trigger_service, sample_cron_trigger, mock_repositories
    ):
        """Test recording failed execution."""
        _, execution_repo = mock_repositories

        mock_execution = TriggerExecution(
            trigger_id=sample_cron_trigger.id,
            status=ExecutionStatus.FAILED,
            execution_time_ms=50,
            error_message="Test error",
        )
        execution_repo.create.return_value = mock_execution

        result = await trigger_service._record_execution_failure(
            sample_cron_trigger.id, "Test error", {"test": "data"}, 50
        )

        assert result.status == ExecutionStatus.FAILED
        assert result.error_message == "Test error"
        assert result.execution_time_ms == 50

    async def test_llm_condition_evaluation_placeholder(self, trigger_service):
        """Test LLM condition evaluation placeholder."""
        llm_condition = {
            "description": "When user sends a file attachment",
            "context_fields": ["request.body"],
        }

        event_data = {"request": {"body": {"document": {"file_name": "test.pdf"}}}}

        # This should return True as a placeholder
        result = await trigger_service._evaluate_llm_condition(llm_condition, event_data)
        assert result is True

    async def test_condition_evaluation_error_handling(self, trigger_service, sample_cron_trigger):
        """Test condition evaluation error handling."""
        # Set up conditions that will cause an error
        sample_cron_trigger.conditions = {"invalid_condition_type": {"bad": "config"}}

        # Should return True (default) when condition evaluation fails
        result = await trigger_service.evaluate_trigger_conditions(sample_cron_trigger, {})
        assert result is True


class TestTriggerExecutionIntegration:
    """Integration tests for trigger execution with TaskService."""

    @pytest.fixture
    def mock_task_service(self):
        """Create mock TaskService."""
        task_service = AsyncMock()

        # Mock task creation
        mock_task = MagicMock()
        mock_task.id = uuid4()
        task_service.create_task_from_params.return_value = mock_task

        return task_service

    async def test_trigger_execution_creates_task(self, mock_task_service):
        """Test that trigger execution creates a task with correct parameters."""
        # This would be an integration test that verifies the full flow
        # from trigger execution to task creation

        trigger_id = uuid4()
        agent_id = uuid4()
        execution_data = {"execution_time": datetime.utcnow().isoformat(), "source": "cron"}

        # Verify task creation was called with correct parameters
        # This test would need actual integration setup
        pass

    async def test_webhook_trigger_execution_with_request_data(self):
        """Test webhook trigger execution with HTTP request data."""
        # This would test the full webhook trigger flow
        # including request parsing and task parameter building
        pass

    async def test_cron_trigger_execution_with_schedule_data(self):
        """Test cron trigger execution with schedule data."""
        # This would test the full cron trigger flow
        # including schedule information in task parameters
        pass
