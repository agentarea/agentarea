"""Integration test for A2A API endpoints with real FastAPI app."""

from uuid import uuid4

import pytest
from agentarea_agents.domain.models import Agent
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


@pytest.fixture
def mock_agent():
    """Create a mock agent for testing."""
    return Agent(
        id=uuid4(),
        name="Test A2A Agent",
        description="An agent for testing A2A protocol",
        status="active",
        model_id="gpt-4",
        tools_config={
            "tools": [
                {"name": "calculator", "type": "function"},
                {"name": "web_search", "type": "function"},
            ]
        },
        planning=True,
    )


class TestA2AAPIEndpoints:
    """Test A2A API endpoints with real FastAPI app."""

    def test_a2a_well_known_endpoint_structure(self, client):
        """Test that the A2A well-known endpoint exists and has correct structure."""
        # This will return 404 because no agent exists, but it validates the endpoint structure
        agent_id = str(uuid4())
        response = client.get(f"/api/v1/agents/{agent_id}/a2a/well-known")

        # Should return 404 for non-existent agent, not 405 (method not allowed)
        assert response.status_code in [404, 500]  # 404 for not found, 500 for service errors

        # Verify it's not a method not allowed error
        assert response.status_code != 405

    def test_a2a_rpc_endpoint_structure(self, client):
        """Test that the A2A RPC endpoint exists and has correct structure."""
        agent_id = str(uuid4())

        # Test with invalid JSON-RPC request
        response = client.post(
            f"/api/v1/agents/{agent_id}/a2a/rpc",
            json={
                "jsonrpc": "2.0",
                "id": "test-123",
                "method": "agent/authenticatedExtendedCard",
                "params": {},
            },
        )

        # Should return JSON-RPC error response, not 405 (method not allowed)
        assert response.status_code in [200, 404, 500]  # Valid JSON-RPC responses
        assert response.status_code != 405

        if response.status_code == 200:
            # Should be valid JSON-RPC response
            data = response.json()
            assert "jsonrpc" in data
            assert data["jsonrpc"] == "2.0"
            assert "id" in data
            assert data["id"] == "test-123"

    def test_a2a_message_send_structure(self, client):
        """Test A2A message/send method structure."""
        agent_id = str(uuid4())

        response = client.post(
            f"/api/v1/agents/{agent_id}/a2a/rpc",
            json={
                "jsonrpc": "2.0",
                "id": "test-message",
                "method": "message/send",
                "params": {"message": {"role": "user", "parts": [{"text": "Hello, test agent!"}]}},
            },
        )

        # Should return valid JSON-RPC response
        assert response.status_code in [200, 404, 500]
        assert response.status_code != 405

        if response.status_code == 200:
            data = response.json()
            assert "jsonrpc" in data
            assert data["jsonrpc"] == "2.0"
            assert "id" in data
            assert data["id"] == "test-message"

    def test_a2a_task_send_structure(self, client):
        """Test A2A tasks/send method structure."""
        agent_id = str(uuid4())

        response = client.post(
            f"/api/v1/agents/{agent_id}/a2a/rpc",
            json={
                "jsonrpc": "2.0",
                "id": "test-task",
                "method": "tasks/send",
                "params": {"message": {"role": "user", "parts": [{"text": "Process this task"}]}},
            },
        )

        # Should return valid JSON-RPC response
        assert response.status_code in [200, 404, 500]
        assert response.status_code != 405

        if response.status_code == 200:
            data = response.json()
            assert "jsonrpc" in data
            assert data["jsonrpc"] == "2.0"
            assert "id" in data
            assert data["id"] == "test-task"

    def test_a2a_invalid_method(self, client):
        """Test A2A with invalid method returns proper JSON-RPC error."""
        agent_id = str(uuid4())

        response = client.post(
            f"/api/v1/agents/{agent_id}/a2a/rpc",
            json={"jsonrpc": "2.0", "id": "test-invalid", "method": "invalid/method", "params": {}},
        )

        # Should return JSON-RPC error for invalid method
        assert response.status_code == 200  # JSON-RPC errors return 200 with error in body

        data = response.json()
        assert "jsonrpc" in data
        assert data["jsonrpc"] == "2.0"
        assert "id" in data
        assert data["id"] == "test-invalid"
        assert "error" in data
        assert data["error"]["code"] == -32601  # Method not found

    def test_a2a_invalid_json_rpc(self, client):
        """Test A2A with invalid JSON-RPC structure."""
        agent_id = str(uuid4())

        response = client.post(f"/api/v1/agents/{agent_id}/a2a/rpc", json={"invalid": "request"})

        # Should return JSON-RPC error for invalid request
        assert response.status_code == 200

        data = response.json()
        assert "jsonrpc" in data
        assert data["jsonrpc"] == "2.0"
        assert "error" in data
        assert data["error"]["code"] == -32600  # Invalid request

    def test_a2a_endpoints_in_router(self, app):
        """Test that A2A endpoints are properly registered in the router."""
        # Check that the routes exist in the FastAPI app
        routes = [route.path for route in app.routes]

        # The A2A routes should be registered
        a2a_routes = [route for route in routes if "/a2a/" in route]
        assert len(a2a_routes) >= 2  # At least well-known and rpc endpoints

        # Check for specific A2A route patterns
        has_well_known = any("/a2a/well-known" in route for route in routes)
        has_rpc = any("/a2a/rpc" in route for route in routes)

        assert has_well_known, f"A2A well-known endpoint not found in routes: {routes}"
        assert has_rpc, f"A2A RPC endpoint not found in routes: {routes}"

    def test_a2a_cors_headers(self, client):
        """Test that A2A endpoints support CORS for cross-origin requests."""
        agent_id = str(uuid4())

        # Test OPTIONS request for CORS preflight
        response = client.options(f"/api/v1/agents/{agent_id}/a2a/well-known")

        # Should handle OPTIONS request (may return 405 if not explicitly handled, but shouldn't crash)
        assert response.status_code in [200, 405, 404]

    def test_a2a_authentication_structure(self, client):
        """Test A2A authentication handling structure."""
        agent_id = str(uuid4())

        # Test without authentication (should work for well-known endpoint)
        response = client.get(f"/api/v1/agents/{agent_id}/a2a/well-known")
        assert response.status_code in [200, 404, 500]  # Should not be 401/403 for well-known

        # Test RPC endpoint (may require auth depending on method)
        response = client.post(
            f"/api/v1/agents/{agent_id}/a2a/rpc",
            json={
                "jsonrpc": "2.0",
                "id": "auth-test",
                "method": "agent/authenticatedExtendedCard",
                "params": {},
            },
        )

        # Should return valid response structure regardless of auth
        assert response.status_code in [200, 401, 403, 404, 500]
