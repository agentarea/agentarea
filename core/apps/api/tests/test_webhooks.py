"""Unit tests for webhook endpoints."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from agentarea_api.api.v1.webhooks import router
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def mock_webhook_manager():
    """Create a mock webhook manager."""
    manager = MagicMock()
    manager.handle_webhook_request = AsyncMock()
    manager.is_healthy = AsyncMock()
    return manager


@pytest.fixture
def app_with_webhooks(mock_webhook_manager):
    """Create a FastAPI app with webhook routes for testing."""
    app = FastAPI()

    # Override the dependency
    async def get_mock_webhook_manager():
        return mock_webhook_manager

    # Include router with dependency override
    app.include_router(router)
    app.dependency_overrides[router.dependencies[0].dependency] = get_mock_webhook_manager

    return app


@pytest.fixture
def client(app_with_webhooks):
    """Create a test client."""
    return TestClient(app_with_webhooks)


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

    def test_handle_webhook_get_success(self, client, mock_webhook_manager):
        """Test successful GET webhook handling."""
        # Setup mock response
        mock_webhook_manager.handle_webhook_request.return_value = {
            "status_code": 200,
            "body": {"status": "success", "message": "Webhook processed successfully"},
        }

        # Make request
        response = client.get("/webhooks/test123?param=value")

        # Verify response
        assert response.status_code == 200
        assert response.json()["status"] == "success"

        # Verify webhook manager was called
        mock_webhook_manager.handle_webhook_request.assert_called_once()
        call_args = mock_webhook_manager.handle_webhook_request.call_args
        assert call_args[1]["webhook_id"] == "test123"
        assert call_args[1]["method"] == "GET"
        assert call_args[1]["query_params"] == {"param": "value"}

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
        """Test webhook handling with invalid JSON."""
        # Setup mock response
        mock_webhook_manager.handle_webhook_request.return_value = {
            "status_code": 200,
            "body": {"status": "success"},
        }

        # Make request with invalid JSON
        response = client.post(
            "/webhooks/test123",
            content='{"invalid": json}',
            headers={"content-type": "application/json"},
        )

        # Should still process (body will be None)
        assert response.status_code == 200

        # Verify webhook manager was called with None body
        mock_webhook_manager.handle_webhook_request.assert_called_once()
        call_args = mock_webhook_manager.handle_webhook_request.call_args
        assert call_args[1]["body"] is None

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
        assert "timestamp" in data

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
        assert "error" in data

    def test_debug_webhook(self, client, mock_webhook_manager):
        """Test webhook debug endpoint."""
        # Make request
        response = client.get("/webhooks/debug/test123")

        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert data["webhook_id"] == "test123"
        assert data["status"] == "registered"
        assert "debug_info" in data

    def test_handle_webhook_all_methods(self, client, mock_webhook_manager):
        """Test that webhook endpoint accepts all HTTP methods."""
        # Setup mock response
        mock_webhook_manager.handle_webhook_request.return_value = {
            "status_code": 200,
            "body": {"status": "success"},
        }

        methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]

        for method in methods:
            response = client.request(method, "/webhooks/test123")

            # All methods should be accepted by the endpoint
            # (actual method validation happens in webhook manager)
            assert response.status_code == 200

    def test_handle_webhook_with_query_params(self, client, mock_webhook_manager):
        """Test webhook handling with query parameters."""
        # Setup mock response
        mock_webhook_manager.handle_webhook_request.return_value = {
            "status_code": 200,
            "body": {"status": "success"},
        }

        # Make request with query parameters
        response = client.get("/webhooks/test123?param1=value1&param2=value2&param1=value3")

        # Verify response
        assert response.status_code == 200

        # Verify webhook manager was called with query params
        mock_webhook_manager.handle_webhook_request.assert_called_once()
        call_args = mock_webhook_manager.handle_webhook_request.call_args
        query_params = call_args[1]["query_params"]

        # FastAPI handles multiple values for same param differently
        # but we should get the query params
        assert "param1" in query_params
        assert "param2" in query_params

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
