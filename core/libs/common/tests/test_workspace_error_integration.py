"""Integration tests for workspace error handling with FastAPI."""

import pytest
from agentarea_common.exceptions import (
    InvalidJWTToken,
    MissingWorkspaceContext,
    WorkspaceAccessDenied,
    WorkspaceResourceNotFound,
    register_workspace_error_handlers,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Create a test FastAPI app with workspace error handlers."""
    app = FastAPI()

    # Register workspace error handlers
    register_workspace_error_handlers(app)

    # Add test endpoints that raise workspace exceptions
    @app.get("/test/access-denied")
    async def test_access_denied():
        raise WorkspaceAccessDenied(
            resource_type="agent",
            resource_id="agent-123",
            current_workspace_id="ws-current",
            resource_workspace_id="ws-other",
        )

    @app.get("/test/resource-not-found")
    async def test_resource_not_found():
        raise WorkspaceResourceNotFound(
            resource_type="task", resource_id="task-123", workspace_id="ws-123"
        )

    @app.get("/test/missing-context")
    async def test_missing_context():
        raise MissingWorkspaceContext(missing_field="workspace_id")

    @app.get("/test/invalid-jwt")
    async def test_invalid_jwt():
        raise InvalidJWTToken(reason="Token expired", token_present=True)

    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


class TestWorkspaceErrorIntegration:
    """Test workspace error handling integration with FastAPI."""

    def test_workspace_access_denied_returns_404(self, client):
        """Test that WorkspaceAccessDenied returns 404."""
        response = client.get("/test/access-denied")

        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "Resource not found"
        assert data["error_code"] == "RESOURCE_NOT_FOUND"
        assert "does not exist or you don't have access" in data["detail"]

    def test_workspace_resource_not_found_returns_404(self, client):
        """Test that WorkspaceResourceNotFound returns 404."""
        response = client.get("/test/resource-not-found")

        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "Resource not found"
        assert data["error_code"] == "RESOURCE_NOT_FOUND"
        assert "task does not exist" in data["detail"]

    def test_missing_workspace_context_returns_400(self, client):
        """Test that MissingWorkspaceContext returns 400."""
        response = client.get("/test/missing-context")

        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "Missing workspace context"
        assert data["error_code"] == "MISSING_CONTEXT"
        assert "workspace_id" in data["detail"]

    def test_invalid_jwt_token_returns_401(self, client):
        """Test that InvalidJWTToken returns 401."""
        response = client.get("/test/invalid-jwt")

        assert response.status_code == 401
        data = response.json()
        assert data["error"] == "Authentication failed"
        assert data["error_code"] == "AUTHENTICATION_FAILED"
        assert "WWW-Authenticate" in response.headers
        assert response.headers["WWW-Authenticate"] == "Bearer"
