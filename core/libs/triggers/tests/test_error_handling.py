"""Tests for comprehensive error handling and logging in the trigger system."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# Mark all async tests
pytestmark = pytest.mark.asyncio

from agentarea_triggers.domain.enums import ExecutionStatus, TriggerType, WebhookType
from agentarea_triggers.domain.models import CronTrigger, TriggerCreate, WebhookTrigger
from agentarea_triggers.logging_utils import (
    DependencyUnavailableError,
    TriggerExecutionError,
    TriggerValidationError,
    WebhookValidationError,
    set_correlation_id,
)
from agentarea_triggers.temporal_schedule_manager import TemporalScheduleManager
from agentarea_triggers.trigger_service import TriggerService
from agentarea_triggers.webhook_manager import DefaultWebhookManager


class TestTriggerServiceErrorHandling:
    """Test error handling in TriggerService."""

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies for TriggerService."""
        return {
            "trigger_repository": AsyncMock(),
            "trigger_execution_repository": AsyncMock(),
            "event_broker": AsyncMock(),
            "agent_repository": AsyncMock(),
            "task_service": AsyncMock(),
            "llm_condition_evaluator": AsyncMock(),
            "temporal_schedule_manager": AsyncMock(),
        }

    @pytest.fixture
    def trigger_service(self, mock_dependencies):
        """Create TriggerService with mocked dependencies."""
        return TriggerService(**mock_dependencies)

    @pytest.fixture
    def sample_cron_trigger_data(self):
        """Sample cron trigger creation data."""
        return TriggerCreate(
            name="Test Cron Trigger",
            description="Test cron trigger",
            agent_id=uuid4(),
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            timezone="UTC",
            created_by="test_user",
        )

    async def test_create_trigger_agent_repository_unavailable(
        self, trigger_service, sample_cron_trigger_data
    ):
        """Test trigger creation when agent repository is unavailable."""
        # Setup - no agent repository
        trigger_service.agent_repository = None

        # Execute and verify - should get TriggerExecutionError wrapping DependencyUnavailableError
        with pytest.raises(TriggerExecutionError) as exc_info:
            await trigger_service.create_trigger(sample_cron_trigger_data)

        assert "Failed to create trigger" in str(exc_info.value)
        assert "Agent repository not available" in str(exc_info.value)

    async def test_create_trigger_agent_not_found(
        self, trigger_service, sample_cron_trigger_data, mock_dependencies
    ):
        """Test trigger creation when agent doesn't exist."""
        # Setup - agent not found
        mock_dependencies["agent_repository"].get.return_value = None

        # Execute and verify - TriggerValidationError should bubble up
        with pytest.raises(TriggerValidationError) as exc_info:
            await trigger_service.create_trigger(sample_cron_trigger_data)

        assert "does not exist" in str(exc_info.value)
        assert exc_info.value.context["agent_id"] == str(sample_cron_trigger_data.agent_id)

    async def test_create_trigger_agent_repository_error(
        self, trigger_service, sample_cron_trigger_data, mock_dependencies
    ):
        """Test trigger creation when agent repository throws error."""
        # Setup - agent repository throws exception
        mock_dependencies["agent_repository"].get.side_effect = Exception(
            "Database connection failed"
        )

        # Execute and verify - should get TriggerExecutionError wrapping DependencyUnavailableError
        with pytest.raises(TriggerExecutionError) as exc_info:
            await trigger_service.create_trigger(sample_cron_trigger_data)

        assert "Failed to create trigger" in str(exc_info.value)
        assert "Error validating agent existence" in str(exc_info.value)

    async def test_create_trigger_temporal_schedule_manager_unavailable(
        self, trigger_service, sample_cron_trigger_data, mock_dependencies
    ):
        """Test cron trigger creation when temporal schedule manager is unavailable."""
        # Setup - valid agent but no temporal schedule manager
        mock_dependencies["agent_repository"].get.return_value = MagicMock()
        mock_dependencies["trigger_repository"].create_from_model.return_value = CronTrigger(
            id=uuid4(),
            name=sample_cron_trigger_data.name,
            description=sample_cron_trigger_data.description,
            agent_id=sample_cron_trigger_data.agent_id,
            trigger_type=TriggerType.CRON,
            is_active=True,
            task_parameters={},
            conditions={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            created_by=sample_cron_trigger_data.created_by,
            cron_expression=sample_cron_trigger_data.cron_expression,
            timezone=sample_cron_trigger_data.timezone,
        )
        trigger_service.temporal_schedule_manager = None

        # Execute and verify - should succeed but log warning about scheduling
        trigger = await trigger_service.create_trigger(sample_cron_trigger_data)
        assert trigger is not None
        assert trigger.trigger_type == TriggerType.CRON

    async def test_record_execution_repository_error(self, trigger_service, mock_dependencies):
        """Test execution recording when repository throws error."""
        # Setup - repository throws exception
        trigger_id = uuid4()
        mock_dependencies["trigger_execution_repository"].create.side_effect = Exception(
            "Database error"
        )

        # Execute and verify
        with pytest.raises(TriggerExecutionError) as exc_info:
            await trigger_service.record_execution(
                trigger_id=trigger_id, status=ExecutionStatus.SUCCESS, execution_time_ms=1000
            )

        assert "Failed to record trigger execution" in str(exc_info.value)
        assert exc_info.value.context["trigger_id"] == str(trigger_id)

    async def test_schedule_cron_trigger_temporal_unavailable(self, trigger_service):
        """Test cron trigger scheduling when temporal manager is unavailable."""
        # Setup - no temporal schedule manager
        trigger_service.temporal_schedule_manager = None
        trigger = CronTrigger(
            id=uuid4(),
            name="Test Trigger",
            description="Test",
            agent_id=uuid4(),
            trigger_type=TriggerType.CRON,
            is_active=True,
            task_parameters={},
            conditions={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            created_by="test",
            cron_expression="0 9 * * *",
            timezone="UTC",
        )

        # Execute and verify
        with pytest.raises(DependencyUnavailableError) as exc_info:
            await trigger_service.schedule_cron_trigger(trigger)

        assert "Temporal schedule manager not available" in str(exc_info.value)
        assert exc_info.value.context["dependency"] == "temporal_schedule_manager"


class TestWebhookManagerErrorHandling:
    """Test error handling in WebhookManager."""

    @pytest.fixture
    def execution_callback(self):
        """Mock execution callback."""
        return AsyncMock()

    @pytest.fixture
    def webhook_manager(self, execution_callback):
        """Create DefaultWebhookManager with mocked callback."""
        return DefaultWebhookManager(execution_callback)

    @pytest.fixture
    def sample_webhook_trigger(self):
        """Sample webhook trigger."""
        return WebhookTrigger(
            id=uuid4(),
            name="Test Webhook",
            description="Test webhook trigger",
            agent_id=uuid4(),
            trigger_type=TriggerType.WEBHOOK,
            is_active=True,
            task_parameters={},
            conditions={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            created_by="test",
            webhook_id="test_webhook_123",
            allowed_methods=["POST"],
            webhook_type=WebhookType.GENERIC,
            validation_rules={
                "required_headers": ["content-type"],
                "content_type": "application/json",
                "body_format": "json",
            },
        )

    async def test_handle_webhook_request_not_found(self, webhook_manager):
        """Test webhook request handling when webhook is not found."""
        # Execute
        response = await webhook_manager.handle_webhook_request(
            webhook_id="nonexistent",
            method="POST",
            headers={"content-type": "application/json"},
            body={"test": "data"},
            query_params={},
        )

        # Verify
        assert response["status_code"] == 400
        assert "not found" in response["body"]["message"]

    async def test_handle_webhook_request_inactive_trigger(
        self, webhook_manager, sample_webhook_trigger
    ):
        """Test webhook request handling when trigger is inactive."""
        # Setup - inactive trigger
        sample_webhook_trigger.is_active = False
        await webhook_manager.register_webhook(sample_webhook_trigger)

        # Execute
        response = await webhook_manager.handle_webhook_request(
            webhook_id=sample_webhook_trigger.webhook_id,
            method="POST",
            headers={"content-type": "application/json"},
            body={"test": "data"},
            query_params={},
        )

        # Verify
        assert response["status_code"] == 400
        assert "inactive" in response["body"]["message"]

    async def test_handle_webhook_request_invalid_method(
        self, webhook_manager, sample_webhook_trigger
    ):
        """Test webhook request handling with invalid HTTP method."""
        # Setup
        await webhook_manager.register_webhook(sample_webhook_trigger)

        # Execute - use GET when only POST is allowed
        response = await webhook_manager.handle_webhook_request(
            webhook_id=sample_webhook_trigger.webhook_id,
            method="GET",
            headers={"content-type": "application/json"},
            body={"test": "data"},
            query_params={},
        )

        # Verify
        assert response["status_code"] == 400
        assert "not allowed" in response["body"]["message"]

    async def test_handle_webhook_request_validation_failure(
        self, webhook_manager, sample_webhook_trigger
    ):
        """Test webhook request handling when validation fails."""
        # Setup
        await webhook_manager.register_webhook(sample_webhook_trigger)

        # Execute - missing required header
        response = await webhook_manager.handle_webhook_request(
            webhook_id=sample_webhook_trigger.webhook_id,
            method="POST",
            headers={},  # Missing content-type header
            body={"test": "data"},
            query_params={},
        )

        # Verify
        assert response["status_code"] == 400
        assert "validation failed" in response["body"]["message"]

    async def test_handle_webhook_request_execution_callback_error(
        self, webhook_manager, sample_webhook_trigger, execution_callback
    ):
        """Test webhook request handling when execution callback fails."""
        # Setup
        await webhook_manager.register_webhook(sample_webhook_trigger)
        execution_callback.execute_webhook_trigger.side_effect = Exception("Execution failed")

        # Execute
        response = await webhook_manager.handle_webhook_request(
            webhook_id=sample_webhook_trigger.webhook_id,
            method="POST",
            headers={"content-type": "application/json"},
            body={"test": "data"},
            query_params={},
        )

        # Verify
        assert response["status_code"] == 400
        assert "execution failed" in response["body"]["message"]

    async def test_apply_validation_rules_json_parsing_error(
        self, webhook_manager, sample_webhook_trigger
    ):
        """Test validation rules with invalid JSON body."""
        # Setup - trigger expects JSON but body is invalid
        sample_webhook_trigger.validation_rules = {"body_format": "json"}

        # Execute
        result = await webhook_manager.apply_validation_rules(
            sample_webhook_trigger,
            {"content-type": "application/json"},
            "invalid json {",  # Invalid JSON
        )

        # Verify
        assert result is False

    async def test_apply_validation_rules_exception_handling(
        self, webhook_manager, sample_webhook_trigger
    ):
        """Test validation rules exception handling."""
        # Setup - trigger with malformed validation rules
        sample_webhook_trigger.validation_rules = {"required_headers": None}  # Invalid type

        # Execute and verify
        with pytest.raises(WebhookValidationError):
            await webhook_manager.apply_validation_rules(
                sample_webhook_trigger, {"content-type": "application/json"}, {"test": "data"}
            )


class TestTemporalScheduleManagerErrorHandling:
    """Test error handling in TemporalScheduleManager."""

    @pytest.fixture
    def temporal_client(self):
        """Mock Temporal client."""
        return AsyncMock()

    @pytest.fixture
    def schedule_manager(self, temporal_client):
        """Create TemporalScheduleManager with mocked client."""
        return TemporalScheduleManager(temporal_client)

    async def test_create_cron_schedule_no_client(self):
        """Test schedule creation when client is unavailable."""
        # Setup - no client
        schedule_manager = TemporalScheduleManager(None)
        trigger_id = uuid4()

        # Execute and verify
        with pytest.raises(DependencyUnavailableError) as exc_info:
            await schedule_manager.create_cron_schedule(
                trigger_id=trigger_id, cron_expression="0 9 * * *"
            )

        assert "Temporal client not available" in str(exc_info.value)
        assert exc_info.value.context["dependency"] == "temporal_client"

    async def test_create_cron_schedule_temporal_error(self, schedule_manager, temporal_client):
        """Test schedule creation when Temporal throws error."""
        # Setup - Temporal client throws error
        from temporalio.exceptions import TemporalError

        temporal_client.create_schedule.side_effect = TemporalError("Schedule already exists")
        trigger_id = uuid4()

        # Execute and verify
        with pytest.raises(TriggerExecutionError) as exc_info:
            await schedule_manager.create_cron_schedule(
                trigger_id=trigger_id, cron_expression="0 9 * * *"
            )

        assert "Temporal error creating schedule" in str(exc_info.value)
        assert exc_info.value.context["trigger_id"] == str(trigger_id)

    async def test_create_cron_schedule_unexpected_error(self, schedule_manager, temporal_client):
        """Test schedule creation with unexpected error."""
        # Setup - unexpected error
        temporal_client.create_schedule.side_effect = ValueError("Invalid argument")
        trigger_id = uuid4()

        # Execute and verify
        with pytest.raises(TriggerExecutionError) as exc_info:
            await schedule_manager.create_cron_schedule(
                trigger_id=trigger_id, cron_expression="0 9 * * *"
            )

        assert "Unexpected error creating schedule" in str(exc_info.value)
        assert exc_info.value.context["original_error"] == "Invalid argument"


class TestCorrelationIdLogging:
    """Test correlation ID functionality in logging."""

    def test_correlation_id_context(self):
        """Test correlation ID context management."""
        from agentarea_triggers.logging_utils import generate_correlation_id, get_correlation_id

        # Test initial state
        assert get_correlation_id() is None

        # Test setting correlation ID
        correlation_id = generate_correlation_id()
        set_correlation_id(correlation_id)
        assert get_correlation_id() == correlation_id

    def test_trigger_logger_correlation_id(self):
        """Test TriggerLogger correlation ID formatting."""
        from agentarea_triggers.logging_utils import TriggerLogger

        # Setup
        logger = TriggerLogger("test")
        correlation_id = "test123"
        set_correlation_id(correlation_id)

        # Test message formatting
        with patch.object(logger.logger, "info") as mock_info:
            logger.info("Test message", trigger_id=uuid4())

            # Verify correlation ID is included in log message
            call_args = mock_info.call_args[0][0]
            assert f"correlation_id={correlation_id}" in call_args
            assert "Test message" in call_args

    def test_trigger_error_correlation_id(self):
        """Test TriggerError correlation ID handling."""
        from agentarea_triggers.logging_utils import TriggerError

        # Setup
        correlation_id = "test123"
        set_correlation_id(correlation_id)

        # Test error creation
        error = TriggerError("Test error", test_context="value")
        assert error.correlation_id == correlation_id
        assert error.context["test_context"] == "value"

        # Test error dictionary conversion
        error_dict = error.to_dict()
        assert error_dict["correlation_id"] == correlation_id
        assert error_dict["context"]["test_context"] == "value"


class TestGracefulDegradation:
    """Test graceful degradation scenarios."""

    @pytest.fixture
    def trigger_service_partial_deps(self):
        """Create TriggerService with some missing dependencies."""
        return TriggerService(
            trigger_repository=AsyncMock(),
            trigger_execution_repository=AsyncMock(),
            event_broker=AsyncMock(),
            agent_repository=None,  # Missing
            task_service=None,  # Missing
            llm_condition_evaluator=None,  # Missing
            temporal_schedule_manager=None,  # Missing
        )

    async def test_graceful_degradation_missing_agent_repository(
        self, trigger_service_partial_deps
    ):
        """Test graceful handling when agent repository is missing."""
        trigger_data = TriggerCreate(
            name="Test Trigger",
            description="Test",
            agent_id=uuid4(),
            trigger_type=TriggerType.WEBHOOK,
            webhook_id="test_webhook",
            created_by="test",
        )

        # Should raise DependencyUnavailableError, not crash
        with pytest.raises(DependencyUnavailableError):
            await trigger_service_partial_deps.create_trigger(trigger_data)

    async def test_graceful_degradation_missing_task_service(self, trigger_service_partial_deps):
        """Test graceful handling when task service is missing."""
        # This would be tested in the execute_trigger method
        # For now, we verify the service can be created without task_service
        assert trigger_service_partial_deps.task_service is None

    async def test_graceful_degradation_missing_temporal_manager(
        self, trigger_service_partial_deps
    ):
        """Test graceful handling when temporal schedule manager is missing."""
        # Verify service can be created without temporal manager
        assert trigger_service_partial_deps.temporal_schedule_manager is None

        # Cron trigger scheduling should fail gracefully
        trigger = CronTrigger(
            id=uuid4(),
            name="Test",
            description="Test",
            agent_id=uuid4(),
            trigger_type=TriggerType.CRON,
            is_active=True,
            task_parameters={},
            conditions={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            created_by="test",
            cron_expression="0 9 * * *",
            timezone="UTC",
        )

        with pytest.raises(DependencyUnavailableError):
            await trigger_service_partial_deps.schedule_cron_trigger(trigger)
