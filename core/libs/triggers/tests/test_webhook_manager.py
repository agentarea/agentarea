"""Unit tests for WebhookManager."""

from datetime import datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_triggers.domain.enums import ExecutionStatus, WebhookType
from agentarea_triggers.domain.models import TriggerExecution, WebhookTrigger
from agentarea_triggers.webhook_manager import (
    DefaultWebhookManager,
    WebhookExecutionCallback,
    WebhookRequestData,
    WebhookValidationResult,
)


class MockWebhookExecutionCallback(WebhookExecutionCallback):
    """Mock webhook execution callback for testing."""

    def __init__(self):
        self.execute_webhook_trigger = AsyncMock()

    async def execute_webhook_trigger(self, webhook_id: str, request_data: dict):
        return await self.execute_webhook_trigger(webhook_id, request_data)


@pytest.fixture
def mock_execution_callback():
    """Create a mock webhook execution callback."""
    return MockWebhookExecutionCallback()


@pytest.fixture
def webhook_manager(mock_execution_callback):
    """Create a DefaultWebhookManager instance for testing."""
    return DefaultWebhookManager(
        execution_callback=mock_execution_callback, event_broker=None, base_url="/webhooks"
    )


@pytest.fixture
def sample_webhook_trigger():
    """Create a sample webhook trigger for testing."""
    return WebhookTrigger(
        id=uuid4(),
        name="Test Webhook",
        description="Test webhook trigger",
        agent_id=uuid4(),
        webhook_id="test_webhook_123",
        allowed_methods=["POST"],
        webhook_type=WebhookType.GENERIC,
        created_by="test_user",
        is_active=True,
    )


@pytest.fixture
def sample_telegram_trigger():
    """Create a sample Telegram webhook trigger for testing."""
    return WebhookTrigger(
        id=uuid4(),
        name="Telegram Bot",
        description="Telegram webhook trigger",
        agent_id=uuid4(),
        webhook_id="telegram_bot_123",
        allowed_methods=["POST"],
        webhook_type=WebhookType.TELEGRAM,
        created_by="test_user",
        is_active=True,
        validation_rules={"required_headers": ["content-type"], "content_type": "application/json"},
    )


class TestWebhookRequestData:
    """Test WebhookRequestData class."""

    def test_webhook_request_data_creation(self):
        """Test creating WebhookRequestData."""
        data = WebhookRequestData(
            webhook_id="test_123",
            method="POST",
            headers={"content-type": "application/json"},
            body={"message": "test"},
            query_params={"param": "value"},
        )

        assert data.webhook_id == "test_123"
        assert data.method == "POST"
        assert data.headers["content-type"] == "application/json"
        assert data.body["message"] == "test"
        assert data.query_params["param"] == "value"
        assert isinstance(data.received_at, datetime)

    def test_webhook_request_data_method_uppercase(self):
        """Test that HTTP method is converted to uppercase."""
        data = WebhookRequestData(
            webhook_id="test_123", method="post", headers={}, body=None, query_params={}
        )

        assert data.method == "POST"


class TestWebhookValidationResult:
    """Test WebhookValidationResult class."""

    def test_valid_result(self):
        """Test creating a valid validation result."""
        result = WebhookValidationResult(is_valid=True, parsed_data={"key": "value"})

        assert result.is_valid is True
        assert result.parsed_data == {"key": "value"}
        assert result.error_message is None

    def test_invalid_result(self):
        """Test creating an invalid validation result."""
        result = WebhookValidationResult(
            is_valid=False, parsed_data={}, error_message="Validation failed"
        )

        assert result.is_valid is False
        assert result.parsed_data == {}
        assert result.error_message == "Validation failed"


class TestDefaultWebhookManager:
    """Test DefaultWebhookManager class."""

    def test_generate_webhook_url(self, webhook_manager):
        """Test generating webhook URL."""
        trigger_id = uuid4()
        url = webhook_manager.generate_webhook_url(trigger_id)

        assert url.startswith("/webhooks/")
        assert len(url.split("/")[-1]) == 16  # Shortened ID

    @pytest.mark.asyncio
    async def test_register_webhook(self, webhook_manager, sample_webhook_trigger):
        """Test registering a webhook."""
        await webhook_manager.register_webhook(sample_webhook_trigger)

        assert sample_webhook_trigger.webhook_id in webhook_manager._registered_webhooks
        assert (
            webhook_manager._registered_webhooks[sample_webhook_trigger.webhook_id]
            == sample_webhook_trigger
        )

    @pytest.mark.asyncio
    async def test_unregister_webhook(self, webhook_manager, sample_webhook_trigger):
        """Test unregistering a webhook."""
        # First register
        await webhook_manager.register_webhook(sample_webhook_trigger)
        assert sample_webhook_trigger.webhook_id in webhook_manager._registered_webhooks

        # Then unregister
        await webhook_manager.unregister_webhook(sample_webhook_trigger.webhook_id)
        assert sample_webhook_trigger.webhook_id not in webhook_manager._registered_webhooks

    @pytest.mark.asyncio
    async def test_validate_webhook_method_allowed(self, webhook_manager, sample_webhook_trigger):
        """Test validating allowed HTTP method."""
        result = await webhook_manager.validate_webhook_method(sample_webhook_trigger, "POST")
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_webhook_method_not_allowed(
        self, webhook_manager, sample_webhook_trigger
    ):
        """Test validating disallowed HTTP method."""
        result = await webhook_manager.validate_webhook_method(sample_webhook_trigger, "GET")
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_webhook_method_case_insensitive(
        self, webhook_manager, sample_webhook_trigger
    ):
        """Test that method validation is case insensitive."""
        result = await webhook_manager.validate_webhook_method(sample_webhook_trigger, "post")
        assert result is True

    @pytest.mark.asyncio
    async def test_apply_validation_rules_no_rules(self, webhook_manager, sample_webhook_trigger):
        """Test validation when no rules are specified."""
        sample_webhook_trigger.validation_rules = {}

        result = await webhook_manager.apply_validation_rules(
            sample_webhook_trigger, {"content-type": "application/json"}, {"test": "data"}
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_apply_validation_rules_required_headers_present(
        self, webhook_manager, sample_telegram_trigger
    ):
        """Test validation when required headers are present."""
        result = await webhook_manager.apply_validation_rules(
            sample_telegram_trigger,
            {"content-type": "application/json", "user-agent": "test"},
            {"test": "data"},
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_apply_validation_rules_required_headers_missing(
        self, webhook_manager, sample_telegram_trigger
    ):
        """Test validation when required headers are missing."""
        result = await webhook_manager.apply_validation_rules(
            sample_telegram_trigger,
            {"user-agent": "test"},  # Missing content-type
            {"test": "data"},
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_apply_validation_rules_content_type_match(
        self, webhook_manager, sample_telegram_trigger
    ):
        """Test validation when content type matches."""
        result = await webhook_manager.apply_validation_rules(
            sample_telegram_trigger,
            {"content-type": "application/json; charset=utf-8"},
            {"test": "data"},
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_apply_validation_rules_content_type_mismatch(
        self, webhook_manager, sample_telegram_trigger
    ):
        """Test validation when content type doesn't match."""
        result = await webhook_manager.apply_validation_rules(
            sample_telegram_trigger, {"content-type": "text/plain"}, {"test": "data"}
        )

        assert result is False

    # Rate limiting tests removed - rate limiting moved to infrastructure layer

    @pytest.mark.asyncio
    async def test_get_webhook_response_success(self, webhook_manager):
        """Test generating success response."""
        response = await webhook_manager.get_webhook_response(True)

        assert response["status_code"] == 200
        assert response["body"]["status"] == "success"
        assert "message" in response["body"]

    @pytest.mark.asyncio
    async def test_get_webhook_response_error(self, webhook_manager):
        """Test generating error response."""
        response = await webhook_manager.get_webhook_response(False, "Test error")

        assert response["status_code"] == 400
        assert response["body"]["status"] == "error"
        assert response["body"]["message"] == "Test error"

    @pytest.mark.asyncio
    async def test_is_healthy(self, webhook_manager):
        """Test health check."""
        result = await webhook_manager.is_healthy()
        assert result is True

    @pytest.mark.asyncio
    async def test_handle_webhook_request_not_found(self, webhook_manager):
        """Test handling request for non-existent webhook."""
        response = await webhook_manager.handle_webhook_request(
            webhook_id="nonexistent",
            method="POST",
            headers={"content-type": "application/json"},
            body={"test": "data"},
            query_params={},
        )

        assert response["status_code"] == 400
        assert "not found" in response["body"]["message"].lower()

    @pytest.mark.asyncio
    async def test_handle_webhook_request_inactive_trigger(
        self, webhook_manager, sample_webhook_trigger
    ):
        """Test handling request for inactive webhook trigger."""
        sample_webhook_trigger.is_active = False
        await webhook_manager.register_webhook(sample_webhook_trigger)

        response = await webhook_manager.handle_webhook_request(
            webhook_id=sample_webhook_trigger.webhook_id,
            method="POST",
            headers={"content-type": "application/json"},
            body={"test": "data"},
            query_params={},
        )

        assert response["status_code"] == 400
        assert "inactive" in response["body"]["message"].lower()

    @pytest.mark.asyncio
    async def test_handle_webhook_request_method_not_allowed(
        self, webhook_manager, sample_webhook_trigger
    ):
        """Test handling request with disallowed method."""
        await webhook_manager.register_webhook(sample_webhook_trigger)

        response = await webhook_manager.handle_webhook_request(
            webhook_id=sample_webhook_trigger.webhook_id,
            method="GET",  # Only POST is allowed
            headers={"content-type": "application/json"},
            body={"test": "data"},
            query_params={},
        )

        assert response["status_code"] == 400
        assert "not allowed" in response["body"]["message"].lower()

    @pytest.mark.asyncio
    async def test_handle_webhook_request_success(
        self, webhook_manager, sample_webhook_trigger, mock_execution_callback
    ):
        """Test successful webhook request handling."""
        # Setup mock execution
        mock_execution = TriggerExecution(
            id=uuid4(),
            trigger_id=sample_webhook_trigger.id,
            executed_at=datetime.utcnow(),
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=100,
        )
        mock_execution_callback.execute_webhook_trigger.return_value = mock_execution

        await webhook_manager.register_webhook(sample_webhook_trigger)

        response = await webhook_manager.handle_webhook_request(
            webhook_id=sample_webhook_trigger.webhook_id,
            method="POST",
            headers={"content-type": "application/json"},
            body={"test": "data"},
            query_params={"param": "value"},
        )

        assert response["status_code"] == 200
        assert response["body"]["status"] == "success"

        # Verify execution callback was called
        mock_execution_callback.execute_webhook_trigger.assert_called_once()
        call_args = mock_execution_callback.execute_webhook_trigger.call_args
        assert call_args[0][0] == sample_webhook_trigger.webhook_id
        assert "webhook_id" in call_args[0][1]
        assert "method" in call_args[0][1]
        assert "headers" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_parse_telegram_webhook(self, webhook_manager, sample_telegram_trigger):
        """Test parsing Telegram webhook data."""
        telegram_data = {
            "update_id": 123456,
            "message": {
                "message_id": 789,
                "from": {"id": 12345, "username": "testuser"},
                "chat": {"id": -67890},
                "date": 1640995200,
                "text": "Hello, bot!",
            },
        }

        request_data = WebhookRequestData(
            webhook_id=sample_telegram_trigger.webhook_id,
            method="POST",
            headers={"content-type": "application/json"},
            body=telegram_data,
            query_params={},
        )

        parsed_data = await webhook_manager._parse_webhook_data(
            sample_telegram_trigger, request_data
        )

        assert parsed_data["webhook_type"] == "telegram"
        assert parsed_data["telegram_update_id"] == 123456
        assert parsed_data["chat_id"] == -67890
        assert parsed_data["user_id"] == 12345
        assert parsed_data["username"] == "testuser"
        assert parsed_data["text"] == "Hello, bot!"
        assert parsed_data["message_id"] == 789
        assert "raw_data" in parsed_data

    @pytest.mark.asyncio
    async def test_parse_generic_webhook(self, webhook_manager, sample_webhook_trigger):
        """Test parsing generic webhook data."""
        request_data = WebhookRequestData(
            webhook_id=sample_webhook_trigger.webhook_id,
            method="POST",
            headers={"content-type": "application/json"},
            body={"custom": "data", "value": 42},
            query_params={"param": "test"},
        )

        parsed_data = await webhook_manager._parse_webhook_data(
            sample_webhook_trigger, request_data
        )

        assert parsed_data["webhook_type"] == "generic"
        assert parsed_data["body"] == {"custom": "data", "value": 42}
        assert parsed_data["raw_data"] == {"custom": "data", "value": 42}
        assert parsed_data["method"] == "POST"
        assert parsed_data["query_params"] == {"param": "test"}


if __name__ == "__main__":
    pytest.main([__file__])
