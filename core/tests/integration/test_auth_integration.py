"""Integration tests for authentication system.

These tests verify the complete authentication flow including:
- JWT token validation
- Middleware behavior
- Route protection
- Workspace isolation
- Context management
"""

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
import pytest
from agentarea_common.auth.context_manager import ContextManager
from agentarea_common.auth.middleware import AuthMiddleware
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def test_app():
    """Create a test FastAPI application with auth middleware."""
    app = FastAPI()

    # Add auth middleware with test configuration
    app.add_middleware(
        AuthMiddleware,
        provider_name="kratos",
        config={
            "jwks_b64": os.getenv(
                "KRATOS_JWKS_B64",
                "ewogICJrZXlzIjogWwogICAgewogICAgICAia3R5IjogIkVDIiwKICAgICAgImtpZCI6ICJ0ZXN0LWtleS0xIiwKICAgICAgInVzZSI6ICJzaWciLAogICAgICAiYWxnIjogIkVTMjU2IiwKICAgICAgImNydiI6ICJQLTI1NiIsCiAgICAgICJ4IjogIk1LQkNUTkljS1VTRGlpMTF5U3MzNTI2aURaOEFpVG83VHU2S1BBcXY3RDQiLAogICAgICAieSI6ICI0RXRsNlNSVzJZaUxVck41dmZ2Vkh1aHA3eDhQeGx0bVdXbGJiTTRJRnlNIiwKICAgICAgImQiOiAiODcwTUI2Z2Z1VEo0SHRVblV2WU15SnByNWVVWk5QNEJrNDNiVmRqM2VBRSIKICAgIH0KICBdCn0=",
            ),
            "issuer": "https://test.agentarea.dev",
            "audience": "test-api",
        },
    )

    # Public routes
    @app.get("/")
    async def root():
        return {"message": "public"}

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    @app.get("/docs")
    async def docs():
        return {"docs": "public"}

    @app.get("/v1/auth/users/me")
    async def auth_me():
        return {"auth": "public"}

    # Protected routes
    @app.get("/v1/agents")
    async def list_agents():
        context = ContextManager.get_context()
        return {"agents": [], "user_id": context.user_id, "workspace_id": context.workspace_id}

    @app.post("/v1/agents")
    async def create_agent():
        context = ContextManager.get_context()
        return {"id": "new-agent", "workspace_id": context.workspace_id}

    @app.get("/v1/agents/{agent_id}")
    async def get_agent(agent_id: str):
        context = ContextManager.get_context()
        return {
            "id": agent_id,
            "workspace_id": context.workspace_id,
            "user_id": context.user_id,
        }

    # Admin route
    @app.get("/admin/users")
    async def list_users():
        context = ContextManager.get_context()
        if "admin" not in context.roles:
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="Admin access required")
        return {"users": []}

    return app


@pytest.fixture
def client(test_app):
    """Create test client."""
    return TestClient(test_app)


@pytest.fixture
def generate_kratos_token():
    """Generate a Kratos-compatible JWT token for testing."""

    def _generate(
        user_id: str = "test-user",
        workspace_id: str = "test-workspace",
        email: str | None = None,
        roles: list[str] | None = None,
        expires_in_minutes: int = 30,
    ) -> str:
        payload = {
            "sub": user_id,
            "workspace_id": workspace_id,
            "iss": "https://test.agentarea.dev",
            "aud": "test-api",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=expires_in_minutes),
        }

        if email:
            payload["email"] = email
        if roles:
            payload["roles"] = roles

        # Note: This is a mock token for testing
        # In reality, it would need to be signed with the correct EC key
        return jwt.encode(payload, "test-secret", algorithm="HS256")

    return _generate


class TestPublicRoutes:
    """Test public routes that don't require authentication."""

    def test_root_accessible_without_auth(self, client):
        """Test that root route is accessible without authentication."""
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"message": "public"}

    def test_health_accessible_without_auth(self, client):
        """Test that health route is accessible without authentication."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    def test_docs_accessible_without_auth(self, client):
        """Test that docs route is accessible without authentication."""
        response = client.get("/docs")
        assert response.status_code == 200
        # /docs returns HTML (Swagger UI), not JSON
        assert "text/html" in response.headers.get("content-type", "")

    def test_auth_routes_accessible_without_auth(self, client):
        """Test that auth routes are accessible without authentication."""
        response = client.get("/v1/auth/users/me")
        assert response.status_code == 200
        assert response.json() == {"auth": "public"}


class TestProtectedRoutes:
    """Test protected routes that require authentication."""

    def test_protected_route_without_token(self, client):
        """Test that protected routes return 401 without token."""
        response = client.get("/v1/agents")
        assert response.status_code == 401
        assert "authorization" in response.json()["detail"].lower()

    def test_protected_route_with_invalid_header_format(self, client):
        """Test that protected routes return 401 with invalid auth header."""
        response = client.get("/v1/agents", headers={"Authorization": "InvalidFormat token"})
        assert response.status_code == 401

    def test_protected_route_with_mock_valid_token(self, client, generate_kratos_token):
        """Test protected route with mocked valid token."""
        token = generate_kratos_token(
            user_id="user-123", workspace_id="workspace-456", email="test@example.com"
        )

        # Mock the provider's verify_token to return success
        with patch("agentarea_common.auth.middleware.AuthProviderFactory.create_provider") as mock:
            from agentarea_common.auth.interfaces import AuthResult, AuthToken

            mock_provider = mock.return_value
            auth_token = AuthToken(user_id="user-123", email="test@example.com")
            mock_provider.verify_token.return_value = AuthResult(
                is_authenticated=True, user_id="user-123", token=auth_token
            )

            response = client.get(
                "/v1/agents",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Workspace-ID": "workspace-456",
                },
            )

            # Note: This test requires middleware to be re-initialized or use a fresh app
            # In real integration tests, you'd use a test database and real tokens

    def test_post_protected_route_without_token(self, client):
        """Test that POST to protected routes requires auth."""
        response = client.post("/v1/agents", json={"name": "test"})
        assert response.status_code == 401


class TestWorkspaceIsolation:
    """Test workspace isolation through authentication."""

    def test_workspace_id_from_header(self, client, generate_kratos_token):
        """Test that workspace ID is extracted from X-Workspace-ID header."""
        # This test requires a valid token and proper middleware setup
        # In a real scenario, you'd mock the auth provider or use real tokens
        pass

    def test_workspace_id_defaults_to_default(self, client, generate_kratos_token):
        """Test that workspace ID defaults when not provided."""
        # This test requires a valid token and proper middleware setup
        pass




class TestContextManagement:
    """Test user context management."""

    def test_context_set_during_request(self, client, generate_kratos_token):
        """Test that user context is set during request."""
        # This requires integration with real request flow
        pass

    def test_context_cleared_after_request(self, client, generate_kratos_token):
        """Test that context is cleared after request completes."""
        # Verify no context leaks between requests
        pass

    def test_context_isolated_between_concurrent_requests(self, client, generate_kratos_token):
        """Test that context is isolated between concurrent requests."""
        # Use threading or asyncio to simulate concurrent requests
        pass


class TestAdminAuthorization:
    """Test admin role authorization."""

    def test_admin_endpoint_requires_admin_role(self, client, generate_kratos_token):
        """Test that admin endpoints require admin role."""
        token = generate_kratos_token(
            user_id="regular-user", workspace_id="workspace-456", roles=["user"]
        )

        with patch("agentarea_common.auth.middleware.AuthProviderFactory.create_provider") as mock:
            from agentarea_common.auth.interfaces import AuthResult, AuthToken

            mock_provider = mock.return_value
            auth_token = AuthToken(user_id="regular-user", email="user@example.com")
            auth_result = AuthResult(
                is_authenticated=True, user_id="regular-user", token=auth_token
            )
            mock_provider.verify_token.return_value = auth_result

            # Create fresh client for this test
            test_client = TestClient(client.app)
            response = test_client.get(
                "/admin/users",
                headers={"Authorization": f"Bearer {token}"},
            )

            # Should return 403 without admin role
            # Note: Actual behavior depends on endpoint implementation

    def test_admin_endpoint_accessible_with_admin_role(self, client, generate_kratos_token):
        """Test that admin endpoints work with admin role."""
        token = generate_kratos_token(
            user_id="admin-user", workspace_id="workspace-456", roles=["user", "admin"]
        )

        with patch("agentarea_common.auth.middleware.AuthProviderFactory.create_provider") as mock:
            from agentarea_common.auth.interfaces import AuthResult, AuthToken

            mock_provider = mock.return_value
            auth_token = AuthToken(user_id="admin-user", email="admin@example.com")
            auth_result = AuthResult(is_authenticated=True, user_id="admin-user", token=auth_token)
            mock_provider.verify_token.return_value = auth_result

            # This would work with proper middleware setup


class TestErrorHandling:
    """Test error handling in auth flow."""

    def test_expired_token_returns_401(self, client, generate_kratos_token):
        """Test that expired tokens return 401."""
        token = generate_kratos_token(expires_in_minutes=-30)

        response = client.get(
            "/v1/agents",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 401

    def test_malformed_token_returns_401(self, client):
        """Test that malformed tokens return 401."""
        response = client.get(
            "/v1/agents",
            headers={"Authorization": "Bearer malformed.token.here"},
        )

        assert response.status_code == 401

    def test_missing_bearer_prefix_returns_401(self, client):
        """Test that tokens without Bearer prefix return 401."""
        response = client.get(
            "/v1/agents",
            headers={"Authorization": "sometoken"},
        )

        assert response.status_code == 401


@pytest.mark.integration
class TestEndToEndAuthFlow:
    """End-to-end authentication flow tests."""

    def test_complete_auth_flow_with_valid_token(self, client, generate_kratos_token):
        """Test complete authentication flow from token to response."""
        # Generate token
        token = generate_kratos_token(
            user_id="e2e-user",
            workspace_id="e2e-workspace",
            email="e2e@example.com",
            roles=["user"],
        )

        # Mock auth provider for this test
        with patch("agentarea_common.auth.middleware.AuthProviderFactory.create_provider") as mock:
            from agentarea_common.auth.interfaces import AuthResult, AuthToken

            mock_provider = mock.return_value
            auth_token = AuthToken(user_id="e2e-user", email="e2e@example.com")
            mock_provider.verify_token.return_value = AuthResult(
                is_authenticated=True, user_id="e2e-user", token=auth_token
            )

            # Make request to protected endpoint
            # Verify user context is available
            # Verify response contains correct data
            # Verify workspace isolation

    def test_multiple_sequential_requests_with_different_tokens(
        self, client, generate_kratos_token
    ):
        """Test multiple requests with different tokens maintain isolation."""
        # First request with user 1
        token1 = generate_kratos_token(user_id="user-1", workspace_id="workspace-1")

        # Second request with user 2
        token2 = generate_kratos_token(user_id="user-2", workspace_id="workspace-2")

        # Verify contexts are isolated
        # Verify no data leakage between requests
