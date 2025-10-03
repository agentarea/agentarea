"""Integration tests for error handling in the trigger system."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_triggers.domain.enums import TriggerType
from agentarea_triggers.domain.models import TriggerCreate
from agentarea_triggers.logging_utils import (
    TriggerExecutionError,
    get_correlation_id,
    set_correlation_id,
)
from agentarea_triggers.trigger_service import TriggerService
from agentarea_triggers.webhook_manager import DefaultWebhookManager

# Mark all async tests
pytestmark = pytest.mark.asyncio


class TestErrorHandlingIntegration:
    """Integration tests for error handling across trigger system components."""

    @pytest.fixture
    def mock_dependencies(self):
        """Create comprehensive mock dependencies."""
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

    async def test_end_to_end_error_propagation(self, trigger_service, mock_dependencies):
        """Test that errors propagate correctly through the entire system."""
        # Setup - simulate database connection failure
        mock_dependencies["trigger_repository"].create_from_model.side_effect = Exception(
            "Database connection lost"
        )
        mock_dependencies["agent_repository"].get.return_value = MagicMock()  # Agent exists

        trigger_data = TriggerCreate(
            name="Test Trigger",
            description="Test",
            agent_id=uuid4(),
            trigger_type=TriggerType.WEBHOOK,
            webhook_id="test_webhook",
            created_by="test_user",
        )

        # Execute and verify error propagation
        with pytest.raises(TriggerExecutionError) as exc_info:
            await trigger_service.create_trigger(trigger_data)

        # Verify error contains original context
        assert "Failed to create trigger" in str(exc_info.value)
        assert "Database connection lost" in str(exc_info.value)
        assert exc_info.value.correlation_id is not None

    async def test_webhook_error_handling_with_correlation(self):
        """Test webhook error handling with correlation ID tracking."""
        # Setup
        execution_callback = AsyncMock()
        webhook_manager = DefaultWebhookManager(execution_callback)

        # Set correlation ID
        correlation_id = "test-correlation-123"
        set_correlation_id(correlation_id)

        # Test webhook not found scenario
        response = await webhook_manager.handle_webhook_request(
            webhook_id="nonexistent",
            method="POST",
            headers={"content-type": "application/json"},
            body={"test": "data"},
            query_params={},
        )

        # Verify error response
        assert response["status_code"] == 400
        assert "not found" in response["body"]["message"]

        # Verify correlation ID is maintained
        assert get_correlation_id() == correlation_id

    async def test_graceful_degradation_scenario(self, mock_dependencies):
        """Test graceful degradation when multiple dependencies are unavailable."""
        # Setup - create service with minimal dependencies
        trigger_service = TriggerService(
            trigger_repository=mock_dependencies["trigger_repository"],
            trigger_execution_repository=mock_dependencies["trigger_execution_repository"],
            event_broker=mock_dependencies["event_broker"],
            agent_repository=None,  # Missing
            task_service=None,  # Missing
            llm_condition_evaluator=None,  # Missing
            temporal_schedule_manager=None,  # Missing
        )

        trigger_data = TriggerCreate(
            name="Test Trigger",
            description="Test",
            agent_id=uuid4(),
            trigger_type=TriggerType.CRON,
            cron_expression="0 9 * * *",
            created_by="test_user",
        )

        # Should fail gracefully with clear error message
        with pytest.raises(TriggerExecutionError) as exc_info:
            await trigger_service.create_trigger(trigger_data)

        assert "Agent repository not available" in str(exc_info.value)

    async def test_error_context_preservation(self, trigger_service, mock_dependencies):
        """Test that error context is preserved through multiple layers."""
        # Setup - simulate agent repository error with specific context
        original_error = Exception("Connection timeout after 30 seconds")
        mock_dependencies["agent_repository"].get.side_effect = original_error

        trigger_data = TriggerCreate(
            name="Test Trigger",
            description="Test",
            agent_id=uuid4(),
            trigger_type=TriggerType.WEBHOOK,
            webhook_id="test_webhook",
            created_by="test_user",
        )

        # Execute and verify context preservation
        with pytest.raises(TriggerExecutionError) as exc_info:
            await trigger_service.create_trigger(trigger_data)

        # Verify original error context is preserved
        error_dict = exc_info.value.to_dict()
        assert error_dict["error_type"] == "TriggerExecutionError"
        assert error_dict["correlation_id"] is not None
        assert "trigger_name" in error_dict["context"]
        assert "agent_id" in error_dict["context"]

    async def test_concurrent_error_handling(self, trigger_service, mock_dependencies):
        """Test error handling under concurrent operations."""
        import asyncio

        # Setup - simulate intermittent failures
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 0:  # Fail every other call
                raise Exception(f"Intermittent failure #{call_count}")
            return MagicMock()

        mock_dependencies["agent_repository"].get.side_effect = side_effect

        # Create multiple trigger creation tasks
        tasks = []
        for i in range(4):
            trigger_data = TriggerCreate(
                name=f"Test Trigger {i}",
                description="Test",
                agent_id=uuid4(),
                trigger_type=TriggerType.WEBHOOK,
                webhook_id=f"test_webhook_{i}",
                created_by="test_user",
            )
            tasks.append(trigger_service.create_trigger(trigger_data))

        # Execute concurrently and collect results
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify that some succeed and some fail with proper error handling
        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]

        # Should have both successes and failures
        assert len(failures) > 0
        assert all(isinstance(f, TriggerExecutionError) for f in failures)

        # Each failure should have proper correlation ID
        for failure in failures:
            assert failure.correlation_id is not None
            assert "Intermittent failure" in str(failure)


class TestLoggingIntegration:
    """Integration tests for logging functionality."""

    def test_correlation_id_propagation(self):
        """Test correlation ID propagation through nested operations."""
        from agentarea_triggers.logging_utils import (
            TriggerLogger,
            generate_correlation_id,
            set_correlation_id,
        )

        # Setup
        logger = TriggerLogger("test")
        correlation_id = generate_correlation_id()
        set_correlation_id(correlation_id)

        # Simulate nested operation logging
        with pytest.LoggingWatcher("agentarea_triggers.logging_utils", level="INFO") as watcher:
            logger.info("Starting operation", trigger_id=uuid4())
            logger.info("Nested operation", task_id=uuid4())
            logger.info("Completing operation")

        # Verify all log messages contain the same correlation ID
        for record in watcher.records:
            assert correlation_id in record.message

    def test_structured_error_logging(self):
        """Test structured error logging with context."""
        from agentarea_triggers.logging_utils import TriggerError

        # Create error with context
        trigger_id = uuid4()
        error = TriggerError(
            "Test error message",
            trigger_id=str(trigger_id),
            operation="test_operation",
            additional_context="test_value",
        )

        # Verify structured error data
        error_dict = error.to_dict()
        assert error_dict["error_type"] == "TriggerError"
        assert error_dict["message"] == "Test error message"
        assert error_dict["context"]["trigger_id"] == str(trigger_id)
        assert error_dict["context"]["operation"] == "test_operation"
        assert error_dict["context"]["additional_context"] == "test_value"
