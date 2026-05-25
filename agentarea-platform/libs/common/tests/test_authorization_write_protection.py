"""Test write protection for system entities via AuthorizationService."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.auth.simple_authorization import SimpleAuthorizationService
from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.schemas.dto import AgentUpdate


@pytest.fixture
def authz():
    return SimpleAuthorizationService()


@pytest.fixture
def regular_user_context():
    return UserContext(
        user_id="user-1",
        workspace_id="ws-1",
        accessible_workspaces=["ws-1", "system"],
    )


@pytest.fixture
def system_agent():
    agent = MagicMock()
    agent.id = UUID("00000000-0000-0000-0000-000000000001")
    agent.name = "System Agent"
    agent.workspace_id = "system"
    agent.description = "System agent"
    agent.model_id = "test-model"
    agent.tools = None
    agent.events_config = None
    agent.planning = None
    return agent


@pytest.fixture
def regular_agent():
    agent = MagicMock()
    agent.id = UUID("11111111-1111-1111-1111-111111111111")
    agent.name = "My Agent"
    agent.workspace_id = "ws-1"
    agent.description = "User agent"
    agent.model_id = "test-model"
    agent.tools = None
    agent.events_config = None
    agent.planning = None
    return agent


def _create_agent_service(user_context, authz):
    """Create AgentService with proper constructor injection."""
    mock_repo_factory = MagicMock()
    mock_repo = AsyncMock()
    mock_repo_factory.create_repository.return_value = mock_repo
    mock_repo_factory.user_context = user_context
    mock_event_broker = AsyncMock()
    service = AgentService(mock_repo_factory, mock_event_broker, authorization_service=authz)
    return service, mock_repo


@pytest.mark.asyncio
async def test_cannot_update_system_agent_from_regular_workspace(
    regular_user_context, system_agent, authz
):
    """Regular users cannot modify system agents."""
    service, mock_repo = _create_agent_service(regular_user_context, authz)
    mock_repo.get.return_value = system_agent
    mock_repo.get_by_id.return_value = system_agent

    with pytest.raises(PermissionError, match="Cannot modify agent"):
        await service.update_agent(id=system_agent.id, payload=AgentUpdate(name="Hacked Name"))


@pytest.mark.asyncio
async def test_cannot_delete_system_agent_from_regular_workspace(
    regular_user_context, system_agent, authz
):
    """Regular users cannot delete system agents."""
    service, mock_repo = _create_agent_service(regular_user_context, authz)
    mock_repo.get.return_value = system_agent
    mock_repo.get_by_id.return_value = system_agent

    with pytest.raises(PermissionError, match="Cannot modify agent"):
        await service.delete_agent(system_agent.id)


@pytest.mark.asyncio
async def test_can_update_own_workspace_agent(
    regular_user_context, regular_agent, authz
):
    """Regular users can modify agents in their own workspace."""
    service, mock_repo = _create_agent_service(regular_user_context, authz)
    mock_repo.get.return_value = regular_agent
    mock_repo.get_by_id.return_value = regular_agent
    mock_repo.update_from_entity.return_value = regular_agent

    result = await service.update_agent(
        id=regular_agent.id, payload=AgentUpdate(name="Updated Name")
    )
    assert result is not None


@pytest.mark.asyncio
async def test_can_delete_own_workspace_agent(
    regular_user_context, regular_agent, authz
):
    """Regular users can delete agents in their own workspace."""
    service, mock_repo = _create_agent_service(regular_user_context, authz)
    mock_repo.get.return_value = regular_agent
    mock_repo.get_by_id.return_value = regular_agent
    mock_repo.delete.return_value = True

    result = await service.delete_agent(regular_agent.id)
    assert result is True


@pytest.mark.asyncio
async def test_authz_denies_cross_workspace_writes(regular_user_context, system_agent, authz):
    """AuthorizationService denies cross-workspace writes."""
    service, mock_repo = _create_agent_service(regular_user_context, authz=authz)
    mock_repo.get.return_value = system_agent
    mock_repo.get_by_id.return_value = system_agent

    with pytest.raises(PermissionError, match="Cannot modify agent"):
        await service.update_agent(id=system_agent.id, payload=AgentUpdate(name="Hacked"))


@pytest.mark.asyncio
async def test_authz_allows_own_workspace(regular_user_context, regular_agent, authz):
    """AuthorizationService allows own workspace writes."""
    service, mock_repo = _create_agent_service(regular_user_context, authz=authz)
    mock_repo.get.return_value = regular_agent
    mock_repo.get_by_id.return_value = regular_agent
    mock_repo.update_from_entity.return_value = regular_agent

    result = await service.update_agent(
        id=regular_agent.id, payload=AgentUpdate(name="Updated")
    )
    assert result is not None
