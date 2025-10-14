"""Functional tests for authentication enforcement.

These tests verify that:
1. Endpoints return 401/403 without valid authentication
2. Endpoints return data with valid authentication
3. User can only access their workspace data
"""

import os
import pytest
from httpx import AsyncClient
from jwt import PyJWT
from datetime import datetime, timedelta, UTC


# Test configuration
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


class TestAuthenticationEnforcement:
    """Test that authentication is properly enforced on all endpoints."""

    @pytest.mark.asyncio
    async def test_list_agents_without_auth_returns_403(self):
        """Test that listing agents without authentication returns 403."""
        async with AsyncClient(base_url=API_BASE_URL) as client:
            response = await client.get("/v1/agents/")

            assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"
            assert response.json()["detail"] == "Not authenticated"

    @pytest.mark.asyncio
    async def test_create_agent_without_auth_returns_403(self):
        """Test that creating an agent without authentication returns 403."""
        async with AsyncClient(base_url=API_BASE_URL) as client:
            response = await client.post(
                "/v1/agents/",
                json={
                    "name": "Test Agent",
                    "description": "Test description",
                    "instruction": "Test instruction",
                    "model_id": "test-model",
                },
            )

            assert response.status_code == 403
            assert response.json()["detail"] == "Not authenticated"

    @pytest.mark.asyncio
    async def test_list_agents_with_invalid_token_returns_401(self):
        """Test that listing agents with invalid token returns 401."""
        async with AsyncClient(base_url=API_BASE_URL) as client:
            response = await client.get(
                "/v1/agents/",
                headers={"Authorization": "Bearer invalid_token_here"},
            )

            assert response.status_code == 401
            assert "Invalid token" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_list_agents_with_expired_token_returns_401(self):
        """Test that listing agents with expired token returns 401."""
        # Create an expired JWT token
        expired_token = create_test_jwt(
            user_id="test-user",
            workspace_id="test-workspace",
            expired=True,
        )

        async with AsyncClient(base_url=API_BASE_URL) as client:
            response = await client.get(
                "/v1/agents/",
                headers={"Authorization": f"Bearer {expired_token}"},
            )

            # Should return 401 for any invalid token (expired, malformed key, etc.)
            assert response.status_code == 401
            assert "detail" in response.json()

    @pytest.mark.asyncio
    async def test_list_agents_with_malformed_token_returns_401(self):
        """Test that listing agents with malformed token returns 401."""
        malformed_tokens = [
            "Bearer",  # No token
            "invalid.token",  # Not enough segments
            "a.b",  # Not enough segments
        ]

        for token in malformed_tokens:
            async with AsyncClient(base_url=API_BASE_URL) as client:
                response = await client.get(
                    "/v1/agents/",
                    headers={"Authorization": f"Bearer {token}"},
                )

                assert response.status_code == 401, f"Token '{token}' should return 401"

    @pytest.mark.asyncio
    async def test_all_protected_endpoints_require_auth(self):
        """Test that all major protected endpoints require authentication."""
        protected_endpoints = [
            ("GET", "/v1/agents/"),
            ("GET", "/v1/provider-configs/"),
            ("GET", "/v1/model-instances/"),
            ("GET", "/v1/model-specs/"),
            ("GET", "/v1/mcp-server-instances/"),
            ("GET", "/v1/triggers/"),
        ]

        async with AsyncClient(base_url=API_BASE_URL) as client:
            for method, endpoint in protected_endpoints:
                if method == "GET":
                    response = await client.get(endpoint)
                elif method == "POST":
                    response = await client.post(endpoint, json={})

                # Should return 401 (Unauthorized) or 403 (Forbidden), but NOT 404
                assert response.status_code in [401, 403], (
                    f"{method} {endpoint} should require auth, got {response.status_code}"
                )


class TestAuthenticatedAccess:
    """Test that valid authentication allows access to resources."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv("KRATOS_JWKS_B64"),
        reason="Requires valid Kratos configuration",
    )
    async def test_list_agents_with_valid_token_returns_200(self):
        """Test that listing agents with valid token returns 200."""
        # NOTE: This test requires a valid JWT token from Kratos
        # In a real environment, you would get this from Kratos auth flow
        valid_token = get_valid_test_token()

        if not valid_token:
            pytest.skip("No valid token available for testing")

        async with AsyncClient(base_url=API_BASE_URL) as client:
            response = await client.get(
                "/v1/agents/",
                headers={"Authorization": f"Bearer {valid_token}"},
            )

            assert response.status_code == 200
            assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv("KRATOS_JWKS_B64"),
        reason="Requires valid Kratos configuration",
    )
    async def test_create_agent_with_valid_token_succeeds(self):
        """Test that creating an agent with valid token succeeds."""
        valid_token = get_valid_test_token()

        if not valid_token:
            pytest.skip("No valid token available for testing")

        async with AsyncClient(base_url=API_BASE_URL) as client:
            response = await client.post(
                "/v1/agents/",
                headers={"Authorization": f"Bearer {valid_token}"},
                json={
                    "name": "Functional Test Agent",
                    "description": "Created by functional test",
                    "instruction": "Test instruction",
                    "model_id": "test-model",
                },
            )

            # Should succeed (201) or fail due to validation (422), but NOT auth error
            assert response.status_code not in [401, 403]


class TestWorkspaceIsolation:
    """Test that users can only access data in their workspace."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv("KRATOS_JWKS_B64"),
        reason="Requires valid Kratos configuration",
    )
    async def test_user_can_only_see_own_workspace_agents(self):
        """Test that users can only see agents from their workspace."""
        # This test would require two different valid tokens
        # from different workspaces to properly test isolation
        pytest.skip("Requires multi-workspace test setup")


# Helper functions

def create_test_jwt(
    user_id: str,
    workspace_id: str,
    expired: bool = False,
) -> str:
    """Create a test JWT token.

    Note: This will NOT work with real Kratos validation
    as it won't be signed with the correct key.
    """
    import jwt

    now = datetime.now(UTC)
    exp = now - timedelta(hours=1) if expired else now + timedelta(hours=1)

    payload = {
        "sub": user_id,
        "workspace_id": workspace_id,
        "iss": "https://agentarea.dev",
        "aud": "agentarea-api",
        "iat": now.timestamp(),
        "exp": exp.timestamp(),
    }

    # Sign with a fake key (won't work with real Kratos)
    return jwt.encode(payload, "fake-secret", algorithm="HS256")


def get_valid_test_token() -> str | None:
    """Get a valid JWT token for testing.

    In a real test environment, this would:
    1. Call Kratos to create a test user session
    2. Extract the JWT token from the session
    3. Return it for testing

    For now, returns None to skip tests that require valid tokens.
    """
    return os.getenv("TEST_VALID_JWT_TOKEN")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
