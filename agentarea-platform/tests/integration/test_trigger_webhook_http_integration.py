"""Integration tests for webhook intake with real HTTP requests.

A request to ``/webhooks/{id}`` is verified and parsed against the trigger's
stream source and recorded as one stream event, answered ``202``. Firing the
trigger from that event is the dispatcher's job; these tests play that part with
``TriggerService.fire`` on the recorded event wherever they check the task.
"""

import asyncio
import hashlib
import hmac
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlencode
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

# Import trigger system components
try:
    from agentarea_triggers.domain.enums import TriggerType, WebhookType
    from agentarea_triggers.domain.models import TriggerCreate
    from agentarea_triggers.trigger_service import TriggerService

    TRIGGERS_AVAILABLE = True
except ImportError:
    TRIGGERS_AVAILABLE = False
    pytest.skip("Triggers not available", allow_module_level=True)

from agentarea_common.auth.test_utils import create_test_user_context
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.events.broker import EventBroker
from agentarea_tasks.task_service import TaskService

from tests.integration.webhook_intake_harness import intake, journal  # noqa: F401

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
        task_service.route_or_submit_task.return_value = mock_task

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
    def user_context(self):
        """Create a test user context for the repository factory."""
        return create_test_user_context(
            user_id="webhook-test-user", workspace_id="webhook-test-workspace"
        )

    @pytest.fixture
    def repository_factory(self, db_session, user_context):
        """Create a repository factory backed by the test db session."""
        return RepositoryFactory(db_session, user_context)

    @pytest.fixture
    async def trigger_service(
        self, repository_factory, mock_event_broker, mock_agent_repository, mock_task_service
    ):
        """Create trigger service with real repositories."""
        service = TriggerService(
            repository_factory=repository_factory,
            event_broker=mock_event_broker,
            task_service=mock_task_service,
            llm_condition_evaluator=None,
            temporal_schedule_manager=None,
        )
        # Swap in the mock agent repository so agent-existence validation
        # doesn't require a real Agent row in the test database.
        service.agent_repository = mock_agent_repository
        return service

    @pytest.fixture
    def webhook_app(self, intake):
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

            # Read the raw bytes first (like api/v1/webhooks.py) so signature
            # verification sees exactly what was sent, then decode the body the
            # way the real endpoint does, so form-encoded payloads such as
            # Slack slash commands reach the parser as a dict.
            raw_body = await request.body()
            content_type = headers.get("content-type", "").lower()
            try:
                if "application/json" in content_type:
                    body = await request.json()
                elif "application/x-www-form-urlencoded" in content_type:
                    body = dict(await request.form())
                else:
                    body = raw_body.decode("utf-8") if raw_body else ""
            except Exception:
                body = {}

            # Process webhook
            response = await intake.handle_webhook_request(
                webhook_id, method, headers, body, query_params, raw_body=raw_body
            )

            return JSONResponse(content=response["body"], status_code=response["status_code"])

        @app.get("/webhooks/{webhook_id}")
        async def handle_webhook_get(webhook_id: str, request: Request):
            """Handle GET webhook requests."""
            method = request.method
            headers = dict(request.headers)
            query_params = dict(request.query_params)

            response = await intake.handle_webhook_request(
                webhook_id, method, headers, {}, query_params
            )

            return JSONResponse(content=response["body"], status_code=response["status_code"])

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
        self, webhook_client, trigger_service, mock_task_service, journal, sample_agent_id
    ):
        """A generic POST is recorded with its request, and fires the trigger from it."""
        trigger_data = TriggerCreate(
            name="Generic POST Webhook",
            description="Test generic webhook with POST",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id=str(uuid4()),
            webhook_type=WebhookType.GENERIC,
            allowed_methods=["POST"],
            task_parameters={
                "text": "Process the incoming webhook payload",
                "webhook_type": "generic",
                "action": "process",
            },
            created_by="test_user",
            workspace_id="webhook-test-workspace",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

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

        assert response.status_code == 202
        assert response.json() == {"status": "accepted", "sequence": 1}

        event = journal.data()
        assert event["method"] == "POST"
        assert event["body"]["message"] == "Hello webhook"
        assert event["headers"]["x-custom-header"] == "test-value"

        # What the dispatcher does with the recorded event.
        await trigger_service.fire(trigger.id, event)
        mock_task_service.route_or_submit_task.assert_called_once()
        task_params = mock_task_service.route_or_submit_task.call_args.args[0].task_parameters
        assert task_params["trigger_id"] == str(trigger.id)
        assert task_params["trigger_type"] == "webhook"
        assert task_params["webhook_type"] == "generic"
        assert task_params["action"] == "process"
        assert task_params["trigger_data"]["body"]["message"] == "Hello webhook"

    async def test_generic_webhook_multiple_methods(
        self, webhook_client, trigger_service, journal, sample_agent_id
    ):
        """Every allowed method is recorded; a method the source does not allow is refused."""
        trigger_data = TriggerCreate(
            name="Multi-Method Webhook",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id=str(uuid4()),
            webhook_type=WebhookType.GENERIC,
            allowed_methods=["POST", "PUT", "PATCH"],
            task_parameters={
                "text": "Process the incoming webhook payload",
                "supports_multiple_methods": True,
            },
            created_by="test_user",
            workspace_id="webhook-test-workspace",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

        post_response = webhook_client.post(
            f"/webhooks/{webhook_id}", json={"method": "POST", "data": "post_data"}
        )
        assert post_response.status_code == 202

        put_response = webhook_client.put(
            f"/webhooks/{webhook_id}", json={"method": "PUT", "data": "put_data"}
        )
        assert put_response.status_code == 202

        patch_response = webhook_client.patch(
            f"/webhooks/{webhook_id}", json={"method": "PATCH", "data": "patch_data"}
        )
        assert patch_response.status_code == 202

        assert [data.data["method"] for _, data, _ in journal.events] == ["POST", "PUT", "PATCH"]

        # All webhook refusals collapse to a generic 400 (no distinct 405), so
        # check the message instead of a dedicated status code.
        get_response = webhook_client.get(f"/webhooks/{webhook_id}")
        assert get_response.status_code == 400
        assert "not allowed" in get_response.json()["message"].lower()
        assert len(journal.events) == 3

    # GitHub Webhook Tests

    async def test_github_webhook_push_event(
        self, webhook_client, trigger_service, mock_task_service, journal, sample_agent_id
    ):
        """A signed GitHub push is recorded once under its delivery id, and fires the trigger."""
        # A GitHub trigger has a registered signature scheme, so an unresolvable
        # secret fails closed; a real webhook_secret + matching signature is
        # required for the request to reach the parser under test.
        secret = "github-webhook-secret"  # noqa: S105  # pragma: allowlist secret
        trigger_data = TriggerCreate(
            name="GitHub Push Webhook",
            description="Handle GitHub push events",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id=str(uuid4()),
            webhook_type=WebhookType.GITHUB,
            allowed_methods=["POST"],
            task_parameters={
                "text": "Deploy the pushed commit to staging",
                "action": "deploy",
                "environment": "staging",
            },
            validation_rules={"required_headers": ["X-GitHub-Event"], "webhook_secret": secret},
            created_by="test_user",
            workspace_id="webhook-test-workspace",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

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
        raw_body = json.dumps(github_payload).encode("utf-8")
        signature = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "12345-67890",
            "X-Hub-Signature-256": signature,
            "User-Agent": "GitHub-Hookshot/abc123",
        }

        response = webhook_client.post(f"/webhooks/{webhook_id}", content=raw_body, headers=headers)
        assert response.status_code == 202
        assert response.json()["status"] == "accepted"

        # GitHub redelivers with the same delivery id: recorded once.
        again = webhook_client.post(f"/webhooks/{webhook_id}", content=raw_body, headers=headers)
        assert again.status_code == 202
        assert again.json() == {"status": "duplicate", "sequence": response.json()["sequence"]}

        [(_, event, event_key)] = journal.events
        assert event_key == "x-github-delivery:12345-67890"
        assert event.type == "push"
        assert event.data["ref"] == "refs/heads/main"
        assert event.data["raw_data"]["repository"]["name"] == "test-repo"
        assert event.data["headers"]["x-github-event"] == "push"
        # A signature over the body is a credential's output; it is not kept.
        assert "x-hub-signature-256" not in event.data["headers"]

        await trigger_service.fire(trigger.id, event.data)
        mock_task_service.route_or_submit_task.assert_called_once()
        task_params = mock_task_service.route_or_submit_task.call_args.args[0].task_parameters
        assert task_params["action"] == "deploy"
        assert task_params["environment"] == "staging"
        assert task_params["trigger_data"]["ref"] == "refs/heads/main"

    async def test_github_webhook_validation_failure(
        self, webhook_client, trigger_service, journal, sample_agent_id
    ):
        """A GitHub request missing a required header is refused and not recorded."""
        # A valid signature is required to reach the (separate) header
        # validation this test targets -- github fails closed without one.
        secret = "github-webhook-secret"  # noqa: S105  # pragma: allowlist secret
        trigger_data = TriggerCreate(
            name="GitHub Webhook with Validation",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id=str(uuid4()),
            webhook_type=WebhookType.GITHUB,
            validation_rules={
                "required_headers": ["X-GitHub-Event", "X-GitHub-Delivery"],
                "webhook_secret": secret,
            },
            created_by="test_user",
            workspace_id="webhook-test-workspace",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

        raw_body = json.dumps({"ref": "refs/heads/main"}).encode("utf-8")
        signature = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        response = webhook_client.post(
            f"/webhooks/{webhook_id}",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": signature,
                # Missing X-GitHub-Delivery header
            },
        )

        assert response.status_code == 400
        assert "validation failed" in response.json()["message"].lower()
        assert journal.events == []

    # Slack Webhook Tests

    async def test_slack_webhook_slash_command(
        self, webhook_client, trigger_service, mock_task_service, journal, sample_agent_id
    ):
        """A signed Slack slash command is recorded, and its text is what the agent is asked."""
        # Slack has a registered signature scheme, so a real signing_secret
        # plus a matching X-Slack-Signature are required to get past the
        # (fail-closed) verification step.
        secret = "slack-signing-secret"  # noqa: S105  # pragma: allowlist secret
        trigger_data = TriggerCreate(
            name="Slack Slash Command",
            description="Handle Slack slash commands",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id=str(uuid4()),
            webhook_type=WebhookType.SLACK,
            allowed_methods=["POST"],
            task_parameters={"platform": "slack", "response_type": "ephemeral"},
            validation_rules={"signing_secret": secret},
            created_by="test_user",
            workspace_id="webhook-test-workspace",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

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
        # Encode the body ourselves so the exact bytes signed match the exact
        # bytes sent (letting httpx encode `data=` would leave that implicit).
        raw_body = urlencode(slack_payload).encode("utf-8")
        timestamp = str(int(datetime.now().timestamp()))
        sig_basestring = f"v0:{timestamp}:{raw_body.decode()}"
        signature = (
            "v0=" + hmac.new(secret.encode(), sig_basestring.encode(), hashlib.sha256).hexdigest()
        )

        response = webhook_client.post(
            f"/webhooks/{webhook_id}",
            content=raw_body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "Slackbot 1.0 (+https://api.slack.com/robots)",
                "X-Slack-Signature": signature,
                "X-Slack-Request-Timestamp": timestamp,
            },
        )

        assert response.status_code == 202
        assert response.json()["status"] == "accepted"
        event = journal.data()
        assert event["method"] == "POST"

        await trigger_service.fire(trigger.id, event)
        mock_task_service.route_or_submit_task.assert_called_once()
        submitted = mock_task_service.route_or_submit_task.call_args.args[0]
        # The slash command's own text is the ask; nothing is set on the trigger.
        assert submitted.query == "staging main"
        assert submitted.task_parameters["platform"] == "slack"
        assert submitted.task_parameters["response_type"] == "ephemeral"

    # Telegram Webhook Tests

    async def test_telegram_webhook_message(
        self, webhook_client, trigger_service, mock_task_service, journal, sample_agent_id
    ):
        """A Telegram update is recorded under its update_id, and fires the trigger."""
        trigger_data = TriggerCreate(
            name="Telegram Bot Webhook",
            description="Handle Telegram bot updates",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id=str(uuid4()),
            webhook_type=WebhookType.TELEGRAM,
            allowed_methods=["POST"],
            task_parameters={"platform": "telegram", "auto_reply": True},
            created_by="test_user",
            workspace_id="webhook-test-workspace",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

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

        response = webhook_client.post(
            f"/webhooks/{webhook_id}",
            json=telegram_payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "TelegramBot (like TwitterBot)",
            },
        )

        assert response.status_code == 202
        assert response.json()["status"] == "accepted"
        [(_, event, event_key)] = journal.events
        assert event_key == "telegram:123456789"
        assert event.data["text"] == "Hello bot! Can you help me?"
        assert event.data["username"] == "testuser"

        await trigger_service.fire(trigger.id, event.data)
        mock_task_service.route_or_submit_task.assert_called_once()
        task_params = mock_task_service.route_or_submit_task.call_args.args[0].task_parameters
        assert task_params["platform"] == "telegram"
        assert task_params["auto_reply"] is True
        assert task_params["trigger_data"]["text"] == "Hello bot! Can you help me?"

    # Error Handling and Edge Cases

    async def test_webhook_not_found(self, webhook_client, journal):
        """A request for a webhook no source answers on is refused."""
        fake_webhook_id = f"fake_{uuid4().hex[:8]}"

        response = webhook_client.post(f"/webhooks/{fake_webhook_id}", json={"test": "data"})

        # All webhook refusals collapse to a generic 400 (no distinct 404), so
        # check the message instead of a dedicated status.
        assert response.status_code == 400
        assert "not found" in response.json()["message"].lower()
        assert journal.events == []

    async def test_webhook_method_not_allowed(
        self, webhook_client, trigger_service, journal, sample_agent_id
    ):
        """A method the source does not allow is refused and not recorded."""
        trigger_data = TriggerCreate(
            name="POST Only Webhook",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id=str(uuid4()),
            allowed_methods=["POST"],
            created_by="test_user",
            workspace_id="webhook-test-workspace",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

        response = webhook_client.get(f"/webhooks/{webhook_id}")

        # All webhook refusals collapse to a generic 400 (no distinct 405), so
        # check the message instead of a dedicated status.
        assert response.status_code == 400
        assert "not allowed" in response.json()["message"].lower()
        assert journal.events == []

    async def test_webhook_malformed_json(self, webhook_client, trigger_service, sample_agent_id):
        """Test webhook with malformed JSON payload."""
        trigger_data = TriggerCreate(
            name="JSON Webhook",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id=str(uuid4()),
            created_by="test_user",
            workspace_id="webhook-test-workspace",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

        response = webhook_client.post(
            f"/webhooks/{webhook_id}",
            data='{"invalid": json}',  # Malformed JSON
            headers={"Content-Type": "application/json"},
        )

        # Should handle gracefully: recorded as received, or refused.
        assert response.status_code in [202, 400]

    async def test_webhook_large_payload(
        self, webhook_client, trigger_service, journal, sample_agent_id
    ):
        """A large payload under the event size limit is recorded whole."""
        trigger_data = TriggerCreate(
            name="Large Payload Webhook",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id=str(uuid4()),
            task_parameters={"text": "Process the incoming webhook payload"},
            created_by="test_user",
            workspace_id="webhook-test-workspace",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

        large_data = {
            "message": "Large payload test",
            "data": ["item_" + str(i) for i in range(1000)],  # 1000 items
            "metadata": {f"key_{i}": f"value_{i}" for i in range(100)},  # 100 key-value pairs
        }

        response = webhook_client.post(
            f"/webhooks/{webhook_id}", json=large_data, headers={"Content-Type": "application/json"}
        )

        assert response.status_code == 202
        assert response.json()["status"] == "accepted"
        assert len(journal.data()["body"]["data"]) == 1000

    async def test_concurrent_webhook_requests(
        self, webhook_client, trigger_service, journal, sample_agent_id
    ):
        """Requests with no delivery id are each recorded: none is mistaken for a repeat."""
        trigger_data = TriggerCreate(
            name="Concurrent Webhook",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id=str(uuid4()),
            task_parameters={"text": "Process the incoming webhook payload"},
            created_by="test_user",
            workspace_id="webhook-test-workspace",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

        async def send_request(request_id: int):
            return webhook_client.post(
                f"/webhooks/{webhook_id}",
                json={"request_id": request_id, "timestamp": datetime.utcnow().isoformat()},
            )

        responses = await asyncio.gather(*[send_request(i) for i in range(5)])

        for response in responses:
            assert response.status_code == 202
            assert response.json()["status"] == "accepted"
        assert sorted(response.json()["sequence"] for response in responses) == [1, 2, 3, 4, 5]
        assert all(key.startswith("recv:") for _, _, key in journal.events)

    async def test_webhook_with_query_parameters(
        self, webhook_client, trigger_service, journal, sample_agent_id
    ):
        """Query parameters are recorded with the event; a credential among them is not."""
        trigger_data = TriggerCreate(
            name="Query Params Webhook",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id=str(uuid4()),
            task_parameters={"text": "Process the incoming webhook payload"},
            created_by="test_user",
            workspace_id="webhook-test-workspace",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

        response = webhook_client.post(
            f"/webhooks/{webhook_id}?source=external&version=1.0&debug=true&token=s3cret",
            json={"message": "Test with query params"},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 202
        assert journal.data()["query_params"] == {
            "source": "external",
            "version": "1.0",
            "debug": "true",
        }

    async def test_webhook_custom_headers_preservation(
        self, webhook_client, trigger_service, journal, sample_agent_id
    ):
        """Custom headers are recorded with the event; credentials among them are not."""
        trigger_data = TriggerCreate(
            name="Custom Headers Webhook",
            agent_id=sample_agent_id,
            trigger_type=TriggerType.WEBHOOK,
            webhook_id=str(uuid4()),
            task_parameters={"text": "Process the incoming webhook payload"},
            created_by="test_user",
            workspace_id="webhook-test-workspace",
        )

        trigger = await trigger_service.create_trigger(trigger_data)
        webhook_id = trigger.webhook_id

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

        assert response.status_code == 202

        # Header names arrive lowercased from the ASGI layer.
        headers = journal.data()["headers"]
        assert headers["x-custom-source"] == "external-system"
        assert headers["x-request-id"] == "req-12345"
        assert headers["user-agent"] == "CustomClient/2.0"
        assert "authorization" not in headers
