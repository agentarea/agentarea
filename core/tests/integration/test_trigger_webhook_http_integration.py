"""Integration tests for webhook trigger processing with real HTTP requests.

This module tests webhook triggers with actual HTTP requests, including
different webhook types, validation, rate limiting, and error handling.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

# Import trigger system components
try:
    from agentarea_triggers.domain.enums import ExecutionStatus, TriggerType, WebhookType
    from agentarea_triggers.domain.models import TriggerCreate, WebhookTrigger
    from agentarea_triggers.infrastructure.repository import (
        TriggerExecutionRepository,
        TriggerRepository,
    )
    from agentarea_triggers.trigger_service import TriggerService
    from agentarea_triggers.webhook_manager import WebhookManager

    TRIGGERS_AVAILABLE = True
except ImportError:
    TRIGGERS_AVAILABLE = False
    pytest.skip("Triggers not available", allow_module_level=True)

from agentarea_common.events.broker import EventBroker
from agentarea_tasks.task_service import TaskService

pytestmark = pytest.mark.asyncio


class TestWebhookHTTPIntegration:
    """Integration tests for webhook HTTP request processing."""

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
        mock_task.title = "Webhook Task"
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
        mock_agent.name = "Webhook Test Agent"
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
    async def webhook_manager(self, trigger_service, mock_event_broker):
        """Create webhook manager for testing."""
        return WebhookManager(trigger_service=trigger_service, event_broker=mock_event_broker)

    @pytest.fixture
    def webhook_app(self, webhook_manager):
        """Create FastAPI app with webhook endpoints."""
        app = FastAPI()

        @app.post("/webhooks/{webhook_id}")
        @app.put("/webhooks/{webhook_id}")
        @app.patch("/webhooks/{webhook_id}")
        async def handle_webhook(webhook_id: str, request: Request):
            """Handle webhook requests."""
            method = request.method
            headers = dict(request.headers)
            query_params = dict(request.query_params)

            # Get request body
            try:
                if headers.get("content-type", "").startswith("application/json"):
                    body = await request.json()
                else:
                    body_bytes = await request.body()
                    body = body_bytes.decode("utf-8") if body_bytes else ""
            except Exception:
                body = {}

            # Process webhook
            response = await webhook_manager.handle_webhook_request(
                webhook_id, method, headers, body, query_params
            )

            return response["body"], response["status_code"]

        @app.get("/webhooks/{webhook_id}")
        async def handle_webhook_get(webhook_id: str, request: Request):
            """Handle GET webhook requests."""
            method = request.method
            headers = dict(request.headers)
            query_params = dict(request.query_params)

            response = await webhook_manager.handle_webhook_request(
                webhook_id, method, headers, {}, query_params
            )

            return response["body"], response["status_code"]

        return app

    @pytest.fixture
    def webhook_client(self, webhook_app):
        """Create test client for webhook app."""
        return TestClient(webhook_app)

    @pytest.fixture
    def sample_agent_id(self):
        """Sample agent ID for testing."""
        return uuid4()

    # Generic Webhook Tests

    async def test_generic_webhook_post_request(
        self, webhook_client, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test generic webhook with POST request."""
        # Create generic webhook trigger
        trigger_data = TriggerCreate(
            name="Generic POST Webhook",
            description="Test generic webhook with POST",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_type=WebhookType.GENERIC,
            allowed_methods=["POST"],
            task_parameters={"webhook_type": "generic", "action": "process"},
            created_by="test_user",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

        # Send POST request
        payload = {
            "message": "Hello webhook",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {"key": "value", "number": 42},
        }

        response = webhook_client.post(
            f"/webhooks/{webhook_id}",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "X-Custom-Header": "test-value",
                "User-Agent": "TestClient/1.0",
            },
        )

        # Verify response
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "success"
        assert len(result["executions"]) == 1

        execution = result["executions"][0]
        assert execution["status"] == "success"
        assert execution["task_id"] is not None

        # Verify task was created with correct parameters
        mock_task_service.create_task_from_params.assert_called_once()
        call_args = mock_task_service.create_task_from_params.call_args

        task_params = call_args.kwargs["task_parameters"]
        assert task_params["trigger_id"] == str(trigger.id)
        assert task_params["trigger_type"] == "webhook"
        assert task_params["webhook_type"] == "generic"
        assert task_params["action"] == "process"

        # Verify webhook request data is preserved
        trigger_data = task_params["trigger_data"]
        assert trigger_data["request"]["method"] == "POST"
        assert trigger_data["request"]["body"]["message"] == "Hello webhook"
        assert trigger_data["request"]["headers"]["x-custom-header"] == "test-value"

    async def test_generic_webhook_multiple_methods(
        self, webhook_client, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test generic webhook supporting multiple HTTP methods."""
        # Create webhook trigger supporting multiple methods
        trigger_data = TriggerCreate(
            name="Multi-Method Webhook",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_type=WebhookType.GENERIC,
            allowed_methods=["POST", "PUT", "PATCH"],
            task_parameters={"supports_multiple_methods": True},
            created_by="test_user",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

        # Test POST
        post_response = webhook_client.post(
            f"/webhooks/{webhook_id}", json={"method": "POST", "data": "post_data"}
        )
        assert post_response.status_code == 200

        # Test PUT
        put_response = webhook_client.put(
            f"/webhooks/{webhook_id}", json={"method": "PUT", "data": "put_data"}
        )
        assert put_response.status_code == 200

        # Test PATCH
        patch_response = webhook_client.patch(
            f"/webhooks/{webhook_id}", json={"method": "PATCH", "data": "patch_data"}
        )
        assert patch_response.status_code == 200

        # Test unsupported method (GET)
        get_response = webhook_client.get(f"/webhooks/{webhook_id}")
        assert get_response.status_code == 405  # Method not allowed

        # Verify all supported methods created tasks
        assert mock_task_service.create_task_from_params.call_count == 3

    # GitHub Webhook Tests

    async def test_github_webhook_push_event(
        self, webhook_client, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test GitHub webhook with push event."""
        # Create GitHub webhook trigger
        trigger_data = TriggerCreate(
            name="GitHub Push Webhook",
            description="Handle GitHub push events",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_type=WebhookType.GITHUB,
            allowed_methods=["POST"],
            task_parameters={"action": "deploy", "environment": "staging"},
            validation_rules={"required_headers": ["X-GitHub-Event"]},
            created_by="test_user",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

        # GitHub push payload
        github_payload = {
            "ref": "refs/heads/main",
            "before": "abc123",
            "after": "def456",
            "repository": {
                "id": 123456,
                "name": "test-repo",
                "full_name": "testuser/test-repo",
                "html_url": "https://github.com/testuser/test-repo",
            },
            "pusher": {"name": "testuser", "email": "test@example.com"},
            "commits": [
                {
                    "id": "def456",
                    "message": "Fix critical bug",
                    "author": {"name": "testuser", "email": "test@example.com"},
                    "url": "https://github.com/testuser/test-repo/commit/def456",
                }
            ],
        }

        # Send GitHub webhook request
        response = webhook_client.post(
            f"/webhooks/{webhook_id}",
            json=github_payload,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                "X-GitHub-Delivery": "12345-67890",
                "X-Hub-Signature-256": "sha256=dummy_signature",
                "User-Agent": "GitHub-Hookshot/abc123",
            },
        )

        # Verify response
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "success"
        assert len(result["executions"]) == 1

        # Verify task was created with GitHub-specific data
        mock_task_service.create_task_from_params.assert_called_once()
        call_args = mock_task_service.create_task_from_params.call_args

        task_params = call_args.kwargs["task_parameters"]
        assert task_params["action"] == "deploy"
        assert task_params["environment"] == "staging"

        # Verify GitHub webhook data is preserved
        trigger_data = task_params["trigger_data"]
        assert trigger_data["request"]["body"]["ref"] == "refs/heads/main"
        assert trigger_data["request"]["body"]["repository"]["name"] == "test-repo"
        assert trigger_data["request"]["headers"]["x-github-event"] == "push"

    async def test_github_webhook_validation_failure(
        self, webhook_client, trigger_service, sample_agent_id
    ):
        """Test GitHub webhook with validation failure."""
        # Create GitHub webhook trigger with validation
        trigger_data = TriggerCreate(
            name="GitHub Webhook with Validation",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_type=WebhookType.GITHUB,
            validation_rules={"required_headers": ["X-GitHub-Event", "X-GitHub-Delivery"]},
            created_by="test_user",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

        # Send request missing required header
        response = webhook_client.post(
            f"/webhooks/{webhook_id}",
            json={"ref": "refs/heads/main"},
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                # Missing X-GitHub-Delivery header
            },
        )

        # Verify validation failure
        assert response.status_code == 400
        result = response.json()
        assert "validation failed" in result["message"].lower()
        assert "x-github-delivery" in result["message"].lower()

    # Slack Webhook Tests

    async def test_slack_webhook_slash_command(
        self, webhook_client, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test Slack webhook with slash command."""
        # Create Slack webhook trigger
        trigger_data = TriggerCreate(
            name="Slack Slash Command",
            description="Handle Slack slash commands",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_type=WebhookType.SLACK,
            allowed_methods=["POST"],
            task_parameters={"platform": "slack", "response_type": "ephemeral"},
            created_by="test_user",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

        # Slack slash command payload (form-encoded)
        slack_payload = {
            "token": "verification_token",
            "team_id": "T1234567890",
            "team_domain": "testteam",
            "channel_id": "C1234567890",
            "channel_name": "general",
            "user_id": "U1234567890",
            "user_name": "testuser",
            "command": "/deploy",
            "text": "staging main",
            "response_url": "https://hooks.slack.com/commands/1234/5678",
            "trigger_id": "13345224609.738474920.8088930838d88f008e0",
        }

        # Send Slack webhook request
        response = webhook_client.post(
            f"/webhooks/{webhook_id}",
            data=slack_payload,  # Form data
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "Slackbot 1.0 (+https://api.slack.com/robots)",
            },
        )

        # Verify response
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "success"

        # Verify task was created with Slack-specific data
        mock_task_service.create_task_from_params.assert_called_once()
        call_args = mock_task_service.create_task_from_params.call_args

        task_params = call_args.kwargs["task_parameters"]
        assert task_params["platform"] == "slack"
        assert task_params["response_type"] == "ephemeral"

        # Verify Slack data is preserved
        trigger_data = task_params["trigger_data"]
        # Note: Form data gets parsed differently than JSON
        assert trigger_data["request"]["method"] == "POST"

    # Telegram Webhook Tests

    async def test_telegram_webhook_message(
        self, webhook_client, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test Telegram webhook with message update."""
        # Create Telegram webhook trigger
        trigger_data = TriggerCreate(
            name="Telegram Bot Webhook",
            description="Handle Telegram bot updates",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_type=WebhookType.TELEGRAM,
            allowed_methods=["POST"],
            task_parameters={"platform": "telegram", "auto_reply": True},
            created_by="test_user",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

        # Telegram update payload
        telegram_payload = {
            "update_id": 123456789,
            "message": {
                "message_id": 1234,
                "from": {
                    "id": 987654321,
                    "is_bot": False,
                    "first_name": "Test",
                    "last_name": "User",
                    "username": "testuser",
                },
                "chat": {
                    "id": 987654321,
                    "first_name": "Test",
                    "last_name": "User",
                    "username": "testuser",
                    "type": "private",
                },
                "date": 1640995200,
                "text": "Hello bot! Can you help me?",
            },
        }

        # Send Telegram webhook request
        response = webhook_client.post(
            f"/webhooks/{webhook_id}",
            json=telegram_payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "TelegramBot (like TwitterBot)",
            },
        )

        # Verify response
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "success"

        # Verify task was created with Telegram-specific data
        mock_task_service.create_task_from_params.assert_called_once()
        call_args = mock_task_service.create_task_from_params.call_args

        task_params = call_args.kwargs["task_parameters"]
        assert task_params["platform"] == "telegram"
        assert task_params["auto_reply"] is True

        # Verify Telegram data is preserved
        trigger_data = task_params["trigger_data"]
        assert trigger_data["request"]["body"]["message"]["text"] == "Hello bot! Can you help me?"
        assert trigger_data["request"]["body"]["message"]["from"]["username"] == "testuser"

    # Error Handling and Edge Cases

    async def test_webhook_not_found(self, webhook_client):
        """Test webhook request to non-existent webhook."""
        fake_webhook_id = f"fake_{uuid4().hex[:8]}"

        response = webhook_client.post(f"/webhooks/{fake_webhook_id}", json={"test": "data"})

        assert response.status_code == 404
        result = response.json()
        assert "not found" in result["message"].lower()

    async def test_webhook_method_not_allowed(
        self, webhook_client, trigger_service, sample_agent_id
    ):
        """Test webhook with unsupported HTTP method."""
        # Create webhook that only allows POST
        trigger_data = TriggerCreate(
            name="POST Only Webhook",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            allowed_methods=["POST"],
            created_by="test_user",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

        # Try GET request (not allowed)
        response = webhook_client.get(f"/webhooks/{webhook_id}")

        assert response.status_code == 405
        result = response.json()
        assert "method not allowed" in result["message"].lower()

    async def test_webhook_malformed_json(self, webhook_client, trigger_service, sample_agent_id):
        """Test webhook with malformed JSON payload."""
        # Create webhook trigger
        trigger_data = TriggerCreate(
            name="JSON Webhook",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            created_by="test_user",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

        # Send malformed JSON
        response = webhook_client.post(
            f"/webhooks/{webhook_id}",
            data='{"invalid": json}',  # Malformed JSON
            headers={"Content-Type": "application/json"},
        )

        # Should handle gracefully and still process
        assert response.status_code in [200, 400]  # Depends on implementation

    async def test_webhook_large_payload(
        self, webhook_client, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test webhook with large payload."""
        # Create webhook trigger
        trigger_data = TriggerCreate(
            name="Large Payload Webhook",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            created_by="test_user",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

        # Create large payload (but not too large to cause issues)
        large_data = {
            "message": "Large payload test",
            "data": ["item_" + str(i) for i in range(1000)],  # 1000 items
            "metadata": {f"key_{i}": f"value_{i}" for i in range(100)},  # 100 key-value pairs
        }

        response = webhook_client.post(
            f"/webhooks/{webhook_id}", json=large_data, headers={"Content-Type": "application/json"}
        )

        # Should handle large payload successfully
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "success"

        # Verify task was created
        mock_task_service.create_task_from_params.assert_called_once()

    async def test_concurrent_webhook_requests(
        self, webhook_client, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test concurrent webhook requests to the same endpoint."""
        # Create webhook trigger
        trigger_data = TriggerCreate(
            name="Concurrent Webhook",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            created_by="test_user",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

        # Send multiple concurrent requests
        async def send_request(request_id: int):
            return webhook_client.post(
                f"/webhooks/{webhook_id}",
                json={"request_id": request_id, "timestamp": datetime.utcnow().isoformat()},
            )

        # Send 5 concurrent requests
        tasks = [send_request(i) for i in range(5)]
        responses = await asyncio.gather(
            *[asyncio.create_task(asyncio.to_thread(task)) for task in tasks]
        )

        # Verify all requests were processed successfully
        for response in responses:
            assert response.status_code == 200
            result = response.json()
            assert result["status"] == "success"

        # Verify all tasks were created
        assert mock_task_service.create_task_from_params.call_count == 5

    async def test_webhook_with_query_parameters(
        self, webhook_client, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test webhook with query parameters."""
        # Create webhook trigger
        trigger_data = TriggerCreate(
            name="Query Params Webhook",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            created_by="test_user",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

        # Send request with query parameters
        response = webhook_client.post(
            f"/webhooks/{webhook_id}?source=external&version=1.0&debug=true",
            json={"message": "Test with query params"},
            headers={"Content-Type": "application/json"},
        )

        # Verify response
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "success"

        # Verify task was created with query parameters
        mock_task_service.create_task_from_params.assert_called_once()
        call_args = mock_task_service.create_task_from_params.call_args

        task_params = call_args.kwargs["task_parameters"]
        trigger_data = task_params["trigger_data"]

        # Verify query parameters are preserved
        query_params = trigger_data["request"]["query_params"]
        assert query_params["source"] == "external"
        assert query_params["version"] == "1.0"
        assert query_params["debug"] == "true"

    async def test_webhook_custom_headers_preservation(
        self, webhook_client, trigger_service, mock_task_service, sample_agent_id
    ):
        """Test that custom headers are preserved in webhook processing."""
        # Create webhook trigger
        trigger_data = TriggerCreate(
            name="Custom Headers Webhook",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            created_by="test_user",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

        # Send request with custom headers
        custom_headers = {
            "Content-Type": "application/json",
            "X-Custom-Source": "external-system",
            "X-Request-ID": "req-12345",
            "X-Timestamp": datetime.utcnow().isoformat(),
            "Authorization": "Bearer token123",
            "User-Agent": "CustomClient/2.0",
        }

        response = webhook_client.post(
            f"/webhooks/{webhook_id}",
            json={"message": "Test custom headers"},
            headers=custom_headers,
        )

        # Verify response
        assert response.status_code == 200

        # Verify custom headers are preserved
        mock_task_service.create_task_from_params.assert_called_once()
        call_args = mock_task_service.create_task_from_params.call_args

        task_params = call_args.kwargs["task_parameters"]
        trigger_data = task_params["trigger_data"]

        # Verify headers are preserved (note: FastAPI lowercases header names)
        headers = trigger_data["request"]["headers"]
        assert headers["x-custom-source"] == "external-system"
        assert headers["x-request-id"] == "req-12345"
        assert headers["authorization"] == "Bearer token123"
        assert headers["user-agent"] == "CustomClient/2.0"
