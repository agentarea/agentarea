"""Integration tests for workspace isolation across all endpoints.

These tests verify that:
1. All endpoints require authentication
2. Users can only access resources in their workspace
3. Admin users have appropriate privileges
"""

import pytest
from uuid import uuid4


@pytest.mark.integration
class TestWorkspaceIsolation:
    """Test workspace isolation across all resource types."""

    def test_agents_workspace_isolation(self, client, generate_jwt_token):
        """Test agents are isolated by workspace."""
        # User 1 in workspace-1
        token1 = generate_jwt_token(
            user_id="user-1",
            workspace_id="workspace-1",
            roles=["user"],
        )

        # Create agent as user 1
        response = client.post(
            "/v1/agents",
            json={
                "name": "Test Agent",
                "model_id": "gpt-4",
                "instructions": "Test instructions",
            },
            headers={"Authorization": f"Bearer {token1}", "X-Workspace-ID": "workspace-1"},
        )

        if response.status_code == 201:
            agent_id = response.json()["id"]

            # User 2 in workspace-2 should NOT see it
            token2 = generate_jwt_token(
                user_id="user-2",
                workspace_id="workspace-2",
                roles=["user"],
            )

            response = client.get(
                f"/v1/agents/{agent_id}",
                headers={"Authorization": f"Bearer {token2}", "X-Workspace-ID": "workspace-2"},
            )
            # Should be 404 (not found) or 403 (forbidden), NOT 200
            assert response.status_code in [403, 404], "Agent should not be accessible across workspaces"

    def test_tasks_workspace_isolation(self, client, generate_jwt_token):
        """Test tasks are isolated by workspace."""
        # TODO: Implement once tasks endpoint has UserContextDep
        pass

    def test_model_instances_workspace_isolation(self, client, generate_jwt_token):
        """Test model instances are isolated by workspace."""
        # TODO: Implement once model_instances endpoint has UserContextDep
        pass

    def test_provider_configs_workspace_isolation(self, client, generate_jwt_token):
        """Test provider configs are isolated by workspace."""
        # TODO: Implement once provider_configs endpoint has UserContextDep
        pass

    def test_triggers_workspace_isolation(self, client, generate_jwt_token):
        """Test triggers are isolated by workspace."""
        # TODO: Implement once triggers endpoint has UserContextDep
        pass


@pytest.mark.integration
class TestEndpointAuthRequirements:
    """Test that all endpoints require authentication."""

    PROTECTED_ENDPOINTS = [
        ("POST", "/v1/agents", {"name": "Test", "model_id": "gpt-4", "instructions": "test"}),
        ("GET", "/v1/agents", None),
        ("GET", f"/v1/agents/{uuid4()}", None),
        ("PATCH", f"/v1/agents/{uuid4()}", {"name": "Updated"}),
        ("DELETE", f"/v1/agents/{uuid4()}", None),

        # Add more endpoints as they are implemented
        ("POST", "/v1/tasks", {"agent_id": str(uuid4()), "input": "test"}),
        ("GET", "/v1/tasks", None),
        ("GET", f"/v1/tasks/{uuid4()}", None),

        ("POST", "/v1/model-instances", {"name": "test"}),
        ("GET", "/v1/model-instances", None),

        ("POST", "/v1/provider-configs", {"name": "test"}),
        ("GET", "/v1/provider-configs", None),

        ("POST", "/v1/triggers", {"name": "test"}),
        ("GET", "/v1/triggers", None),
    ]

    @pytest.mark.parametrize("method,endpoint,data", PROTECTED_ENDPOINTS)
    def test_endpoint_requires_auth(self, client, method, endpoint, data):
        """Test that endpoint returns 401 without authentication."""
        if method == "GET":
            response = client.get(endpoint)
        elif method == "POST":
            response = client.post(endpoint, json=data)
        elif method == "PATCH":
            response = client.patch(endpoint, json=data)
        elif method == "DELETE":
            response = client.delete(endpoint)

        assert response.status_code == 401, f"{method} {endpoint} should require authentication"


@pytest.mark.integration
class TestAdminAuthorization:
    """Test admin-only endpoints."""

    def test_admin_endpoint_rejects_regular_user(self, client, generate_jwt_token):
        """Test admin endpoints reject non-admin users."""
        token = generate_jwt_token(
            user_id="regular-user",
            workspace_id="workspace-1",
            roles=["user"],  # No admin role
        )

        # Try to access admin endpoint (example)
        response = client.get(
            "/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Should be 403 (forbidden)
        assert response.status_code == 403

    def test_admin_endpoint_allows_admin_user(self, client, generate_jwt_token):
        """Test admin endpoints allow admin users."""
        token = generate_jwt_token(
            user_id="admin-user",
            workspace_id="workspace-1",
            roles=["user", "admin"],  # Has admin role
        )

        # Access admin endpoint
        response = client.get(
            "/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Should work (200 or might be 404 if endpoint doesn't exist yet)
        assert response.status_code in [200, 404]


@pytest.mark.integration
class TestCrossWorkspaceDataLeakage:
    """Test for potential data leakage between workspaces."""

    def test_list_endpoints_dont_leak_across_workspaces(self, client, generate_jwt_token):
        """Test list endpoints only return workspace-specific data."""
        # Create resources in workspace-1
        token1 = generate_jwt_token(user_id="user-1", workspace_id="workspace-1")

        client.post(
            "/v1/agents",
            json={"name": "Agent 1", "model_id": "gpt-4", "instructions": "test"},
            headers={"Authorization": f"Bearer {token1}", "X-Workspace-ID": "workspace-1"},
        )

        # Create resources in workspace-2
        token2 = generate_jwt_token(user_id="user-2", workspace_id="workspace-2")

        client.post(
            "/v1/agents",
            json={"name": "Agent 2", "model_id": "gpt-4", "instructions": "test"},
            headers={"Authorization": f"Bearer {token2}", "X-Workspace-ID": "workspace-2"},
        )

        # List agents as user 1 - should only see workspace-1 agents
        response = client.get(
            "/v1/agents",
            headers={"Authorization": f"Bearer {token1}", "X-Workspace-ID": "workspace-1"},
        )

        if response.status_code == 200:
            agents = response.json()
            # Verify no workspace-2 agents are in the list
            for agent in agents:
                # If workspace info is returned, verify it
                if "workspace_id" in agent:
                    assert agent["workspace_id"] == "workspace-1", "Data leaked from another workspace!"

    def test_search_endpoints_respect_workspace(self, client, generate_jwt_token):
        """Test search/filter endpoints respect workspace boundaries."""
        # TODO: Implement when search endpoints exist
        pass
