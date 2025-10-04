"""Simple test to verify A2A is working with proper authentication."""

from uuid import uuid4

import pytest
from agentarea_api.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Create FastAPI app for testing."""
    return create_app()


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


class TestA2AWorking:
    """Test that A2A endpoints are working correctly."""

    def test_a2a_well_known_with_dev_auth(self, client):
        """Test A2A well-known endpoint with development authentication."""
        agent_id = str(uuid4())

        # Use development mode authentication
        headers = {"x-user-id": "test_user"}

        response = client.get(f"/api/v1/agents/{agent_id}/a2a/well-known", headers=headers)

        # Should return 404 for non-existent agent (not 401 for auth)
        assert response.status_code == 404

        # Verify it's a proper error response
        error_data = response.json()
        assert "detail" in error_data
        assert (
            "not found" in error_data["detail"].lower()
            or "does not exist" in error_data["detail"].lower()
        )

    def test_a2a_rpc_with_dev_auth(self, client):
        """Test A2A RPC endpoint with development authentication."""
        agent_id = str(uuid4())

        headers = {"x-user-id": "test_user"}

        response = client.post(
            f"/api/v1/agents/{agent_id}/a2a/rpc",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": "test-123",
                "method": "agent/authenticatedExtendedCard",
                "params": {},
            },
        )

        # Should return JSON-RPC response (200) with error for non-existent agent
        assert response.status_code == 200

        data = response.json()
        assert "jsonrpc" in data
        assert data["jsonrpc"] == "2.0"
        assert "id" in data
        assert data["id"] == "test-123"

        # Should have error for non-existent agent
        assert "error" in data
        assert data["error"]["code"] == -32602  # Agent not found

    def test_a2a_message_send_with_dev_auth(self, client):
        """Test A2A message/send with development authentication."""
        agent_id = str(uuid4())

        headers = {"x-user-id": "test_user"}

        response = client.post(
            f"/api/v1/agents/{agent_id}/a2a/rpc",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": "test-message",
                "method": "message/send",
                "params": {"message": {"role": "user", "parts": [{"text": "Hello, test agent!"}]}},
            },
        )

        # Should return JSON-RPC response
        assert response.status_code == 200

        data = response.json()
        assert "jsonrpc" in data
        assert data["jsonrpc"] == "2.0"
        assert "id" in data
        assert data["id"] == "test-message"

        # Should have error for non-existent agent
        assert "error" in data
        assert data["error"]["code"] == -32602  # Agent not found

    def test_a2a_invalid_method_with_dev_auth(self, client):
        """Test A2A with invalid method returns proper JSON-RPC error."""
        agent_id = str(uuid4())

        headers = {"x-user-id": "test_user"}

        response = client.post(
            f"/api/v1/agents/{agent_id}/a2a/rpc",
            headers=headers,
            json={"jsonrpc": "2.0", "id": "test-invalid", "method": "invalid/method", "params": {}},
        )

        # Should return JSON-RPC error for invalid method
        assert response.status_code == 200

        data = response.json()
        assert "jsonrpc" in data
        assert data["jsonrpc"] == "2.0"
        assert "id" in data
        assert data["id"] == "test-invalid"
        assert "error" in data
        assert data["error"]["code"] == -32601  # Method not found

    def test_a2a_authentication_required(self, client):
        """Test that A2A endpoints require authentication."""
        agent_id = str(uuid4())

        # Test without any authentication
        response = client.get(f"/api/v1/agents/{agent_id}/a2a/well-known")
        assert response.status_code == 401  # Unauthorized

        response = client.post(
            f"/api/v1/agents/{agent_id}/a2a/rpc",
            json={"jsonrpc": "2.0", "id": "test", "method": "message/send", "params": {}},
        )
        assert response.status_code == 401  # Unauthorized

    def test_a2a_endpoints_registered(self, app):
        """Test that A2A endpoints are properly registered."""
        routes = [route.path for route in app.routes]

        # Check for A2A routes
        a2a_routes = [route for route in routes if "/a2a/" in route]
        assert len(a2a_routes) >= 2  # At least well-known and rpc

        # Verify specific endpoints exist
        has_well_known = any("/a2a/well-known" in route for route in routes)
        has_rpc = any("/a2a/rpc" in route for route in routes)

        assert has_well_known, "A2A well-known endpoint not registered"
        assert has_rpc, "A2A RPC endpoint not registered"
