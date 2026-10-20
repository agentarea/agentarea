"""Unit tests for webhook endpoints."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentarea_api.api import rate_limit
from agentarea_api.api.deps.services import get_public_webhook_manager
from agentarea_api.api.v1.webhooks import router
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.testing.flows import MainFlow
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import RedisError


@pytest.fixture
def mock_webhook_manager():
    """Create a mock webhook manager."""
    manager = MagicMock()
    manager.handle_webhook_request = AsyncMock()
    manager.is_healthy = AsyncMock()
    return manager


@pytest.fixture
def mock_user_context():
    context = MagicMock()
    context.user_id = "test_user"
    context.workspace_id = "test_workspace"
    return context


@pytest.fixture
def app_with_webhooks(mock_webhook_manager, mock_user_context):
    """Create a FastAPI app with webhook routes for testing."""
    app = FastAPI()

    # Override the dependency
    async def get_mock_webhook_manager():
        return mock_webhook_manager

    async def get_mock_user_context():
        return mock_user_context

    # Include router with dependency override
    app.include_router(router)
    app.dependency_overrides[get_public_webhook_manager] = get_mock_webhook_manager
    app.dependency_overrides[get_user_context] = get_mock_user_context

    return app


@pytest.fixture
def client(app_with_webhooks):
    """Create a test client."""
    return TestClient(app_with_webhooks)


@pytest.fixture(autouse=True)
def rate_limit_redis(monkeypatch):
    class FakeRedis:
        async def eval(self, *_args):
            return [1, 0]

    monkeypatch.setattr(rate_limit, "_get_redis_client", lambda: FakeRedis())


@pytest.mark.flow(MainFlow.WEBHOOKS)
class TestWebhookEndpoints:
    """Test webhook API endpoints."""

    def test_handle_webhook_post_success(self, client, mock_webhook_manager):
        """Test successful POST webhook handling."""
        # Setup mock response
        mock_webhook_manager.handle_webhook_request.return_value = {
            "status_code": 200,
            "body": {"status": "success", "message": "Webhook processed successfully"},
        }

        # Make request
        response = client.post(
            "/webhooks/test123",
            json={"message": "test data"},
            headers={"content-type": "application/json"},
        )

        # Verify response
        assert response.status_code == 200
        assert response.json()["status"] == "success"

        # Verify webhook manager was called
        mock_webhook_manager.handle_webhook_request.assert_called_once()
        call_args = mock_webhook_manager.handle_webhook_request.call_args
        assert call_args[1]["webhook_id"] == "test123"
        assert call_args[1]["method"] == "POST"
        assert call_args[1]["body"] == {"message": "test data"}
        assert json.loads(call_args[1]["raw_body"]) == {"message": "test data"}

    def test_a_get_never_reaches_the_intake(self, client, mock_webhook_manager):
        response = client.get("/webhooks/test123?param=value")

        assert response.status_code == 405
        mock_webhook_manager.handle_webhook_request.assert_not_called()

    def test_handle_webhook_form_data(self, client, mock_webhook_manager):
        """Test webhook handling with form data."""
        # Setup mock response
        mock_webhook_manager.handle_webhook_request.return_value = {
            "status_code": 200,
            "body": {"status": "success", "message": "Webhook processed successfully"},
        }

        # Make request with form data
        response = client.post(
            "/webhooks/test123",
            data={"field1": "value1", "field2": "value2"},
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

        # Verify response
        assert response.status_code == 200
        assert response.json()["status"] == "success"

        # Verify webhook manager was called
        mock_webhook_manager.handle_webhook_request.assert_called_once()
        call_args = mock_webhook_manager.handle_webhook_request.call_args
        assert call_args[1]["webhook_id"] == "test123"
        assert call_args[1]["method"] == "POST"
        assert isinstance(call_args[1]["body"], dict)

    def test_handle_webhook_error_response(self, client, mock_webhook_manager):
        """Test webhook handling with error response."""
        # Setup mock error response
        mock_webhook_manager.handle_webhook_request.return_value = {
            "status_code": 400,
            "body": {"status": "error", "message": "Webhook validation failed"},
        }

        # Make request
        response = client.post("/webhooks/test123", json={"invalid": "data"})

        # Verify response
        assert response.status_code == 400
        assert response.json()["status"] == "error"
        assert "validation failed" in response.json()["message"].lower()

    def test_handle_webhook_manager_exception(self, client, mock_webhook_manager):
        """Test webhook handling when manager raises exception."""
        # Setup mock to raise exception
        mock_webhook_manager.handle_webhook_request.side_effect = Exception("Manager error")

        # Make request
        response = client.post("/webhooks/test123", json={"test": "data"})

        # Verify response
        assert response.status_code == 500
        assert response.json()["status"] == "error"
        assert "internal server error" in response.json()["message"].lower()

    def test_handle_webhook_invalid_json(self, client, mock_webhook_manager):
        """A JSON body that does not parse is refused before the intake sees it."""
        response = client.post(
            "/webhooks/test123",
            content='{"invalid": json}',
            headers={"content-type": "application/json"},
        )

        assert response.status_code == 400
        assert response.json()["status"] == "error"
        mock_webhook_manager.handle_webhook_request.assert_not_called()

    def test_webhook_health_check_healthy(self, client, mock_webhook_manager):
        """Test webhook health check when healthy."""
        # Setup mock response
        mock_webhook_manager.is_healthy.return_value = True

        # Make request
        response = client.get("/webhooks/health")

        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "webhook-manager"

    def test_webhook_health_check_unhealthy(self, client, mock_webhook_manager):
        """Test webhook health check when unhealthy."""
        # Setup mock response
        mock_webhook_manager.is_healthy.return_value = False

        # Make request
        response = client.get("/webhooks/health")

        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["service"] == "webhook-manager"

    def test_webhook_health_check_exception(self, client, mock_webhook_manager):
        """Test webhook health check when manager raises exception."""
        # Setup mock to raise exception
        mock_webhook_manager.is_healthy.side_effect = Exception("Health check failed")

        # Make request
        response = client.get("/webhooks/health")

        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["service"] == "webhook-manager"

    def test_only_post_reaches_the_intake(self, client, mock_webhook_manager):
        mock_webhook_manager.handle_webhook_request.return_value = {
            "status_code": 202,
            "body": {"status": "accepted"},
        }

        for method in ["GET", "PUT", "PATCH", "DELETE"]:
            assert client.request(method, "/webhooks/test123").status_code == 405
        assert client.post("/webhooks/test123", json={}).status_code == 202
        mock_webhook_manager.handle_webhook_request.assert_awaited_once()

    def test_handle_webhook_with_custom_headers(self, client, mock_webhook_manager):
        """Test webhook handling with custom headers."""
        # Setup mock response
        mock_webhook_manager.handle_webhook_request.return_value = {
            "status_code": 200,
            "body": {"status": "success"},
        }

        # Make request with custom headers
        custom_headers = {
            "x-custom-header": "custom-value",
            "x-webhook-signature": "signature123",
            "user-agent": "TestBot/1.0",
        }

        response = client.post("/webhooks/test123", json={"test": "data"}, headers=custom_headers)

        # Verify response
        assert response.status_code == 200

        # Verify webhook manager was called with headers
        mock_webhook_manager.handle_webhook_request.assert_called_once()
        call_args = mock_webhook_manager.handle_webhook_request.call_args
        headers = call_args[1]["headers"]

        # Check that custom headers are included
        assert "x-custom-header" in headers
        assert headers["x-custom-header"] == "custom-value"
        assert "x-webhook-signature" in headers
        assert headers["x-webhook-signature"] == "signature123"


if __name__ == "__main__":
    pytest.main([__file__])


def test_webhook_rate_limit_returns_429_after_limit(client, mock_webhook_manager, monkeypatch):
    class FakeRedis:
        def __init__(self):
            self.counts = {}

        async def eval(self, _script, _num_keys, key, limit, _ttl):
            count = self.counts.get(key, 0) + 1
            self.counts[key] = count
            allowed = count <= int(limit)
            return [int(allowed), 0 if allowed else 60]

    fake_redis = FakeRedis()
    monkeypatch.setattr(rate_limit, "_get_redis_client", lambda: fake_redis)
    monkeypatch.setattr(
        rate_limit,
        "get_settings",
        lambda: SimpleNamespace(
            triggers=SimpleNamespace(WEBHOOK_RATE=1),
        ),
    )
    mock_webhook_manager.handle_webhook_request.return_value = {
        "status_code": 200,
        "body": {"status": "success"},
    }

    first = client.post("/webhooks/long-enough-webhook-key", json={"event": "first"})
    second = client.post("/webhooks/long-enough-webhook-key", json={"event": "second"})
    independent = client.post(
        "/webhooks/another-long-enough-webhook-key",
        json={"event": "independent"},
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert int(second.headers["retry-after"]) > 0
    assert independent.status_code == 200
    assert mock_webhook_manager.handle_webhook_request.await_count == 2


def test_webhook_rate_limit_fails_open_when_redis_is_unavailable(
    client, mock_webhook_manager, monkeypatch
):
    class UnavailableRedis:
        async def eval(self, *_args):
            raise RedisError("unavailable")

    monkeypatch.setattr(rate_limit, "_get_redis_client", lambda: UnavailableRedis())
    monkeypatch.setattr(
        rate_limit,
        "get_settings",
        lambda: SimpleNamespace(
            triggers=SimpleNamespace(WEBHOOK_RATE=1),
        ),
    )
    mock_webhook_manager.handle_webhook_request.return_value = {
        "status_code": 200,
        "body": {"status": "success"},
    }

    response = client.post("/webhooks/long-enough-webhook-key", json={"event": "request"})

    assert response.status_code == 200
    mock_webhook_manager.handle_webhook_request.assert_awaited_once()
