"""Integration tests for A2A agent discovery functionality."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_agents.domain.models import Agent
from agentarea_api.api.v1.a2a_auth import A2AAuthContext
from agentarea_api.api.v1.agents_a2a import (
    A2AValidationError,
    get_agent_well_known,
    handle_agent_card,
    validate_agent_exists,
)
from agentarea_common.utils.types import AgentCard
from fastapi import Request


@pytest.mark.asyncio
class TestA2AAgentDiscovery:
    """Test A2A agent discovery functionality."""

    @pytest.fixture
    def mock_agent_service(self):
        """Create a mock agent service."""
        service = AsyncMock()
        return service

    @pytest.fixture
    def mock_auth_context(self):
        """Create a mock A2A auth context."""
        return A2AAuthContext(
            authenticated=True,
            auth_method="bearer",
            user_id="test_user",
            workspace_id="test_workspace",
            permissions=["read", "execute"],
            metadata={},
        )

    @pytest.fixture
    def sample_agent(self):
        """Create a sample agent for testing."""
        return Agent(
            id=uuid4(),
            name="Test Agent",
            description="A test agent for A2A discovery",
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

    @pytest.fixture
    def minimal_agent(self):
        """Create a minimal agent for testing."""
        return Agent(
            id=uuid4(),
            name="Minimal Agent",
            description="",
            status="active",
            model_id=None,
            tools_config=None,
            planning=False,
        )

    @pytest.fixture
    def inactive_agent(self):
        """Create an inactive agent for testing."""
        return Agent(
            id=uuid4(),
            name="Inactive Agent",
            description="An inactive agent",
            status="inactive",
            model_id="gpt-3.5-turbo",
            tools_config=None,
            planning=False,
        )

    async def test_validate_agent_exists_success(self, mock_agent_service, sample_agent):
        """Test successful agent validation."""
        mock_agent_service.get.return_value = sample_agent

        # Should not raise any exception
        await validate_agent_exists(mock_agent_service, sample_agent.id)

        mock_agent_service.get.assert_called_once_with(sample_agent.id)

    async def test_validate_agent_exists_not_found(self, mock_agent_service):
        """Test agent validation when agent doesn't exist."""
        agent_id = uuid4()
        mock_agent_service.get.return_value = None

        with pytest.raises(A2AValidationError) as exc_info:
            await validate_agent_exists(mock_agent_service, agent_id)

        assert exc_info.value.code == -32602
        assert str(agent_id) in exc_info.value.message
        assert "does not exist" in exc_info.value.message

    async def test_validate_agent_exists_inactive(self, mock_agent_service, inactive_agent):
        """Test agent validation when agent is inactive."""
        mock_agent_service.get.return_value = inactive_agent

        with pytest.raises(A2AValidationError) as exc_info:
            await validate_agent_exists(mock_agent_service, inactive_agent.id)

        assert exc_info.value.code == -32602
        assert "not available" in exc_info.value.message
        assert "inactive" in exc_info.value.message

    async def test_validate_agent_exists_service_error(self, mock_agent_service):
        """Test agent validation when service throws an error."""
        agent_id = uuid4()
        mock_agent_service.get.side_effect = Exception("Database error")

        with pytest.raises(A2AValidationError) as exc_info:
            await validate_agent_exists(mock_agent_service, agent_id)

        assert exc_info.value.code == -32603
        assert "Failed to validate agent availability" in exc_info.value.message

    async def test_handle_agent_card_full_featured_agent(
        self, mock_agent_service, sample_agent, mock_auth_context
    ):
        """Test agent card retrieval for a full-featured agent."""
        mock_agent_service.get.return_value = sample_agent

        response = await handle_agent_card(
            request_id="test-123",
            params={},
            agent_service=mock_agent_service,
            agent_id=sample_agent.id,
            base_url="https://api.example.com",
            auth_context=mock_auth_context,
        )

        # Verify response structure
        assert response.jsonrpc == "2.0"
        assert response.id == "test-123"
        assert response.result is not None

        agent_card = response.result
        assert isinstance(agent_card, AgentCard)
        assert agent_card.name == "Test Agent"
        assert agent_card.description == "A test agent for A2A discovery"
        assert agent_card.url == f"https://api.example.com/api/v1/agents/{sample_agent.id}/a2a/rpc"
        assert agent_card.version == "1.0.0"

        # Verify capabilities
        assert agent_card.capabilities.streaming is True
        assert agent_card.capabilities.push_notifications is False
        assert agent_card.capabilities.state_transition_history is True

        # Verify skills - should have 3 skills for full-featured agent
        assert len(agent_card.skills) == 3
        skill_ids = [skill.id for skill in agent_card.skills]
        assert "text-processing" in skill_ids
        assert "tool-execution" in skill_ids
        assert "task-planning" in skill_ids

        # Verify provider includes agent URL
        assert agent_card.provider.organization == "AgentArea"
        assert agent_card.provider.url == f"https://api.example.com/api/v1/agents/{sample_agent.id}"

    async def test_handle_agent_card_minimal_agent(
        self, mock_agent_service, minimal_agent, mock_auth_context
    ):
        """Test agent card retrieval for a minimal agent."""
        mock_agent_service.get.return_value = minimal_agent

        response = await handle_agent_card(
            request_id="test-456",
            params={},
            agent_service=mock_agent_service,
            agent_id=minimal_agent.id,
            base_url="https://api.example.com",
            auth_context=mock_auth_context,
        )

        agent_card = response.result
        assert agent_card.name == "Minimal Agent"
        assert "language model" in agent_card.description  # Default description

        # Verify skills - should only have text-processing for minimal agent
        assert len(agent_card.skills) == 1
        assert agent_card.skills[0].id == "text-processing"

        # Verify provider reflects minimal configuration
        assert agent_card.provider.organization == "AgentArea"
        assert "language model" in agent_card.description

    async def test_handle_agent_card_nonexistent_agent(self, mock_agent_service, mock_auth_context):
        """Test agent card retrieval for non-existent agent."""
        agent_id = uuid4()
        mock_agent_service.get.return_value = None

        response = await handle_agent_card(
            request_id="test-789",
            params={},
            agent_service=mock_agent_service,
            agent_id=agent_id,
            base_url="https://api.example.com",
            auth_context=mock_auth_context,
        )

        # Should return error response
        assert response.jsonrpc == "2.0"
        assert response.id == "test-789"
        assert response.error is not None
        assert response.error.code == -32602
        assert "does not exist" in response.error.message

    async def test_get_agent_well_known_success(
        self, mock_agent_service, sample_agent, mock_auth_context
    ):
        """Test well-known endpoint for agent discovery."""
        mock_agent_service.get.return_value = sample_agent

        # Create mock request
        mock_request = MagicMock(spec=Request)
        mock_request.client.host = "127.0.0.1"
        mock_request.headers.get.return_value = "test-user-agent"

        agent_card = await get_agent_well_known(
            agent_id=sample_agent.id,
            request=mock_request,
            auth_context=mock_auth_context,
            agent_service=mock_agent_service,
        )

        # Verify agent card structure
        assert isinstance(agent_card, AgentCard)
        assert agent_card.name == "Test Agent"
        assert agent_card.description == "A test agent for A2A discovery"
        assert agent_card.url == f"/api/v1/agents/{sample_agent.id}/a2a/rpc"

        # Verify current agent data is included in description and skills
        assert "A test agent for A2A discovery" in agent_card.description
        assert agent_card.provider.organization == "AgentArea"

        # Verify skills based on agent configuration
        assert len(agent_card.skills) == 3
        skill_ids = [skill.id for skill in agent_card.skills]
        assert "text-processing" in skill_ids
        assert "tool-execution" in skill_ids
        assert "task-planning" in skill_ids

    async def test_get_agent_well_known_agent_not_found(
        self, mock_agent_service, mock_auth_context
    ):
        """Test well-known endpoint when agent doesn't exist."""
        agent_id = uuid4()
        mock_agent_service.get.return_value = None

        mock_request = MagicMock(spec=Request)
        mock_request.client.host = "127.0.0.1"
        mock_request.headers.get.return_value = "test-user-agent"

        with pytest.raises(Exception) as exc_info:  # Should raise HTTPException
            await get_agent_well_known(
                agent_id=agent_id,
                request=mock_request,
                auth_context=mock_auth_context,
                agent_service=mock_agent_service,
            )

        # Should be an HTTPException with 404 status
        assert hasattr(exc_info.value, "status_code")
        assert exc_info.value.status_code == 404

    async def test_agent_discovery_includes_availability_status(
        self, mock_agent_service, mock_auth_context
    ):
        """Test that agent discovery includes current availability status."""
        # Test with different agent statuses
        test_cases = [
            ("active", True),
            ("available", True),
            ("ready", True),
            ("inactive", False),
            ("maintenance", False),
            ("disabled", False),
        ]

        for status, should_be_available in test_cases:
            agent = Agent(
                id=uuid4(),
                name=f"Agent {status}",
                description=f"Agent with {status} status",
                status=status,
                model_id="gpt-4",
                tools_config=None,
                planning=False,
            )

            mock_agent_service.get.return_value = agent

            if should_be_available:
                # Should succeed for available agents
                response = await handle_agent_card(
                    request_id="test",
                    params={},
                    agent_service=mock_agent_service,
                    agent_id=agent.id,
                    base_url="https://api.example.com",
                    auth_context=mock_auth_context,
                )
                assert response.result is not None
                if status != "active":
                    assert f"Status: {status}" in response.result.description
            else:
                # Should fail for unavailable agents
                response = await handle_agent_card(
                    request_id="test",
                    params={},
                    agent_service=mock_agent_service,
                    agent_id=agent.id,
                    base_url="https://api.example.com",
                    auth_context=mock_auth_context,
                )
                assert response.error is not None
                assert response.error.code == -32602
                assert "not available" in response.error.message
