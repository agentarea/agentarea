"""Installing/forking a catalog agent must grant the caller the Keto ``owners``
tuple, exactly like creating an agent does.

Without the grant a catalog-installed agent has no access-control owner, so the user who
installed it would be 403'd on (or not see) their own row once Keto is enabled.
The grant lives at the API composition layer (the OSS ``AuthorizationService`` is
deliberately infrastructure-free), so these tests assert the endpoint performs it.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.domain.models import Agent
from agentarea_api.api.deps.services import get_agent_service
from agentarea_api.main import app
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.testing.flows import MainFlow
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def mock_user_context():
    context = MagicMock()
    context.user_id = "test_user"
    context.workspace_id = "test_workspace"
    return context


@pytest.fixture
def forked_agent():
    return Agent(
        id=uuid4(),
        name="Customer Support",
        slug="customer-support",
        status="active",
        instruction="help",
        model_id="m1",
        registry_item_id=str(uuid4()),
    )


@pytest.fixture
def mock_agent_service(forked_agent):
    service = AsyncMock(spec=AgentService)
    service.install_catalog_agent.return_value = forked_agent
    service.update_agent.return_value = forked_agent
    service.get_with_skills.return_value = forked_agent
    return service


@pytest.fixture(autouse=True)
def override_dependencies(mock_agent_service, mock_user_context):
    async def _override_agent_service():
        return mock_agent_service

    async def _override_user_context():
        return mock_user_context

    app.dependency_overrides[get_agent_service] = _override_agent_service
    app.dependency_overrides[get_user_context] = _override_user_context
    yield
    app.dependency_overrides.pop(get_agent_service, None)
    app.dependency_overrides.pop(get_user_context, None)


@pytest.fixture
def captured_grant(monkeypatch):
    grant = AsyncMock()
    monkeypatch.setattr("agentarea_api.api.v1.agents.grant_resource_owner", grant)
    return grant


@pytest.mark.flow(MainFlow.AUTH_WORKSPACE_SCOPING)
@pytest.mark.asyncio
async def test_install_agent_grants_owner_tuple(
    async_client, mock_agent_service, forked_agent, captured_grant
):
    resp = await async_client.post(f"/v1/agents/{uuid4()}/install")

    assert resp.status_code == 200
    mock_agent_service.install_catalog_agent.assert_awaited_once()
    mock_agent_service.get_with_skills.assert_awaited_once_with(forked_agent.id)
    captured_grant.assert_awaited_once_with(
        resource_id=forked_agent.id,
        workspace_id="test_workspace",
        user_id="test_user",
    )


@pytest.mark.flow(MainFlow.AUTH_WORKSPACE_SCOPING)
@pytest.mark.asyncio
async def test_update_agent_grants_owner_tuple(
    async_client, mock_agent_service, forked_agent, captured_grant, monkeypatch
):
    # Editing an un-installed catalog agent forks a tenant copy; ownership of the
    # resulting row must be asserted (idempotent for plain edits). The edit-permission
    # check is a separate PermissionService concern, stubbed here.
    monkeypatch.setattr("agentarea_api.api.v1.agents.require_permission", AsyncMock())
    # Approval-flag overlay reads the DB; irrelevant to the ownership grant asserted here.
    monkeypatch.setattr("agentarea_api.api.v1.agents._overlay_approval_flags", AsyncMock())
    resp = await async_client.patch(f"/v1/agents/{uuid4()}", json={"name": "Renamed"})

    assert resp.status_code == 200
    mock_agent_service.get_with_skills.assert_awaited_once_with(forked_agent.id)
    captured_grant.assert_awaited_once_with(
        resource_id=forked_agent.id,
        workspace_id="test_workspace",
        user_id="test_user",
    )
