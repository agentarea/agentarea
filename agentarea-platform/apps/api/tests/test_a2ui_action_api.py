"""Tests for A2UI action endpoint — workspace isolation and lifecycle guards."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.application.temporal_workflow_service import TemporalWorkflowService
from agentarea_api.api.deps.services import get_agent_service, get_temporal_workflow_service
from agentarea_api.main import app
from agentarea_common.auth.dependencies import get_user_context
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def mock_agent_service():
    return AsyncMock(spec=AgentService)


@pytest.fixture
def mock_workflow_service():
    return AsyncMock(spec=TemporalWorkflowService)


@pytest.fixture
def mock_user_context():
    context = MagicMock()
    context.user_id = "test_user"
    context.workspace_id = "test_workspace"
    return context


@pytest.fixture(autouse=True)
def override_dependencies(mock_agent_service, mock_workflow_service, mock_user_context):
    async def _override_agent_service():
        return mock_agent_service

    async def _override_workflow_service():
        return mock_workflow_service

    async def _override_user_context():
        return mock_user_context

    app.dependency_overrides[get_agent_service] = _override_agent_service
    app.dependency_overrides[get_temporal_workflow_service] = _override_workflow_service
    app.dependency_overrides[get_user_context] = _override_user_context
    yield
    app.dependency_overrides.pop(get_agent_service, None)
    app.dependency_overrides.pop(get_temporal_workflow_service, None)
    app.dependency_overrides.pop(get_user_context, None)


def _make_agent(a2ui_enabled=True):
    agent = MagicMock()
    agent.id = uuid4()
    agent.name = "Test Agent"
    agent.a2ui_enabled = a2ui_enabled
    return agent


SAMPLE_ACTION = {
    "name": "submitForm",
    "surface_id": "s1",
    "source_component_id": "submit_button",
    "context": {"email": "user@example.com"},
}


class TestA2UIActionEndpoint:
    """Test POST /v1/agents/{agent_id}/tasks/{task_id}/a2ui/action"""

    @pytest.mark.asyncio
    async def test_send_action_success(
        self, async_client, mock_agent_service, mock_workflow_service
    ):
        """Action accepted when agent exists, a2ui enabled, task running."""
        agent = _make_agent(a2ui_enabled=True)
        mock_agent_service.get.return_value = agent
        mock_workflow_service.get_workflow_status.return_value = {"status": "running"}
        mock_workflow_service.send_a2ui_action.return_value = True

        task_id = uuid4()
        response = await async_client.post(
            f"/v1/agents/{agent.id}/tasks/{task_id}/a2ui/action",
            json=SAMPLE_ACTION,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert data["action_name"] == "submitForm"

        mock_workflow_service.send_a2ui_action.assert_called_once_with(
            f"agent-task-{task_id}", SAMPLE_ACTION
        )

    @pytest.mark.asyncio
    async def test_agent_not_found_returns_404(
        self, async_client, mock_agent_service
    ):
        """Workspace-scoped get returns None → 404.

        This is the core workspace isolation test: AgentService.get() uses
        WorkspaceScopedMixin, so agents from other workspaces are invisible.
        """
        mock_agent_service.get.return_value = None

        response = await async_client.post(
            f"/v1/agents/{uuid4()}/tasks/{uuid4()}/a2ui/action",
            json=SAMPLE_ACTION,
        )

        assert response.status_code == 404
        assert "Agent not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_a2ui_not_enabled_returns_400(
        self, async_client, mock_agent_service
    ):
        """Agent exists but a2ui_enabled=False → 400."""
        agent = _make_agent(a2ui_enabled=False)
        mock_agent_service.get.return_value = agent

        response = await async_client.post(
            f"/v1/agents/{agent.id}/tasks/{uuid4()}/a2ui/action",
            json=SAMPLE_ACTION,
        )

        assert response.status_code == 400
        assert "A2UI enabled" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_task_not_found_returns_404(
        self, async_client, mock_agent_service, mock_workflow_service
    ):
        """Workflow status 'unknown' → task not found."""
        agent = _make_agent(a2ui_enabled=True)
        mock_agent_service.get.return_value = agent
        mock_workflow_service.get_workflow_status.return_value = {"status": "unknown"}

        response = await async_client.post(
            f"/v1/agents/{agent.id}/tasks/{uuid4()}/a2ui/action",
            json=SAMPLE_ACTION,
        )

        assert response.status_code == 404
        assert "Task not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_completed_task_returns_400(
        self, async_client, mock_agent_service, mock_workflow_service
    ):
        """Cannot send action to a completed task."""
        agent = _make_agent(a2ui_enabled=True)
        mock_agent_service.get.return_value = agent
        mock_workflow_service.get_workflow_status.return_value = {"status": "completed"}

        response = await async_client.post(
            f"/v1/agents/{agent.id}/tasks/{uuid4()}/a2ui/action",
            json=SAMPLE_ACTION,
        )

        assert response.status_code == 400
        assert "completed" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_failed_task_returns_400(
        self, async_client, mock_agent_service, mock_workflow_service
    ):
        """Cannot send action to a failed task."""
        agent = _make_agent(a2ui_enabled=True)
        mock_agent_service.get.return_value = agent
        mock_workflow_service.get_workflow_status.return_value = {"status": "failed"}

        response = await async_client.post(
            f"/v1/agents/{agent.id}/tasks/{uuid4()}/a2ui/action",
            json=SAMPLE_ACTION,
        )

        assert response.status_code == 400
        assert "failed" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_cancelled_task_returns_400(
        self, async_client, mock_agent_service, mock_workflow_service
    ):
        """Cannot send action to a cancelled task."""
        agent = _make_agent(a2ui_enabled=True)
        mock_agent_service.get.return_value = agent
        mock_workflow_service.get_workflow_status.return_value = {"status": "cancelled"}

        response = await async_client.post(
            f"/v1/agents/{agent.id}/tasks/{uuid4()}/a2ui/action",
            json=SAMPLE_ACTION,
        )

        assert response.status_code == 400
        assert "cancelled" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_workflow_signal_failure_returns_500(
        self, async_client, mock_agent_service, mock_workflow_service
    ):
        """send_a2ui_action returns False → 500."""
        agent = _make_agent(a2ui_enabled=True)
        mock_agent_service.get.return_value = agent
        mock_workflow_service.get_workflow_status.return_value = {"status": "running"}
        mock_workflow_service.send_a2ui_action.return_value = False

        response = await async_client.post(
            f"/v1/agents/{agent.id}/tasks/{uuid4()}/a2ui/action",
            json=SAMPLE_ACTION,
        )

        assert response.status_code == 500
        assert "Failed to send action" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_workflow_exception_returns_500(
        self, async_client, mock_agent_service, mock_workflow_service
    ):
        """Unexpected exception → 500 with generic message."""
        agent = _make_agent(a2ui_enabled=True)
        mock_agent_service.get.return_value = agent
        mock_workflow_service.get_workflow_status.side_effect = RuntimeError("temporal down")

        response = await async_client.post(
            f"/v1/agents/{agent.id}/tasks/{uuid4()}/a2ui/action",
            json=SAMPLE_ACTION,
        )

        assert response.status_code == 500
        assert "Internal server error" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_missing_required_field_returns_422(self, async_client, mock_agent_service):
        """Action payload without required 'name' field → 422."""
        agent = _make_agent(a2ui_enabled=True)
        mock_agent_service.get.return_value = agent

        response = await async_client.post(
            f"/v1/agents/{agent.id}/tasks/{uuid4()}/a2ui/action",
            json={"surface_id": "s1"},  # missing 'name'
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_oversized_name_returns_422(self, async_client, mock_agent_service):
        """Action name exceeding 128 chars → 422."""
        agent = _make_agent(a2ui_enabled=True)
        mock_agent_service.get.return_value = agent

        response = await async_client.post(
            f"/v1/agents/{agent.id}/tasks/{uuid4()}/a2ui/action",
            json={"name": "x" * 200, "surface_id": "s1"},
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_extra_fields_rejected_returns_422(self, async_client, mock_agent_service):
        """Extra fields in action payload → 422."""
        agent = _make_agent(a2ui_enabled=True)
        mock_agent_service.get.return_value = agent

        response = await async_client.post(
            f"/v1/agents/{agent.id}/tasks/{uuid4()}/a2ui/action",
            json={**SAMPLE_ACTION, "evil_field": "injection"},
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_workspace_isolation_via_agent_service(
        self, async_client, mock_agent_service
    ):
        """Verify that workspace isolation is enforced through agent_service.get().

        The agent service uses WorkspaceScopedMixin which filters by workspace_id
        from UserContext. An agent from another workspace will not be found,
        preventing cross-workspace A2UI action injection.
        """
        # Simulate agent not in caller's workspace
        mock_agent_service.get.return_value = None

        other_workspace_agent_id = uuid4()
        response = await async_client.post(
            f"/v1/agents/{other_workspace_agent_id}/tasks/{uuid4()}/a2ui/action",
            json=SAMPLE_ACTION,
        )

        assert response.status_code == 404
        # Verify agent_service.get was called (workspace scoping happens there)
        mock_agent_service.get.assert_called_once_with(other_workspace_agent_id)
