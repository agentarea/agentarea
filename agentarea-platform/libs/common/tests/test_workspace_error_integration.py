"""Integration tests for workspace error handling with FastAPI."""

import pytest
from agentarea_common.exceptions import (
    InvalidJWTToken,
    MissingWorkspaceContext,
    WorkspaceAccessDenied,
    WorkspaceResourceNotFound,
    register_error_handlers,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Create a test FastAPI app with the unified error handlers."""
    app = FastAPI()

    # Register the unified error handlers
    register_error_handlers(app)

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
        """WorkspaceAccessDenied -> 404 problem+json, generic non-leaking detail."""
        response = client.get("/test/access-denied")

        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")
        data = response.json()
        assert data["status"] == 404
        assert data["code"] == "not_found"
        assert "does not exist or you don't have access" in data["detail"]
        # Internal workspace ids must not leak into the response body.
        assert "ws-other" not in response.text

    def test_workspace_resource_not_found_returns_404(self, client):
        """WorkspaceResourceNotFound -> 404 problem+json."""
        response = client.get("/test/resource-not-found")

        assert response.status_code == 404
        data = response.json()
        assert data["status"] == 404
        assert data["code"] == "not_found"
        assert "task does not exist" in data["detail"]

    def test_missing_workspace_context_returns_400(self, client):
        """MissingWorkspaceContext -> 400 problem+json."""
        response = client.get("/test/missing-context")

        assert response.status_code == 400
        data = response.json()
        assert data["status"] == 400
        assert data["code"] == "missing_context"
        assert "workspace_id" in data["detail"]

    def test_invalid_jwt_token_returns_401(self, client):
        """InvalidJWTToken -> 401 problem+json with a Bearer challenge."""
        response = client.get("/test/invalid-jwt")

        assert response.status_code == 401
        data = response.json()
        assert data["status"] == 401
        assert data["code"] == "authentication_failed"
        assert "WWW-Authenticate" in response.headers
        assert response.headers["WWW-Authenticate"].startswith("Bearer")
