"""Integration test for A2A agent discovery with real services."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.domain.models import Agent
from agentarea_api.api.v1.a2a_auth import A2AAuthContext
from agentarea_api.api.v1.agents_a2a import get_agent_well_known, handle_agent_card
from agentarea_common.utils.types import AgentCard
from fastapi import Request


@pytest.mark.asyncio
class TestA2AAgentDiscoveryIntegration:
    """Integration test for A2A agent discovery functionality."""

    async def test_agent_discovery_with_real_agent_data(self):
        """Test agent discovery returns current agent data correctly."""
        # Create a realistic agent
        agent = Agent(
            id=uuid4(),
            name="Production Agent",
            description="A production-ready AI agent",
            status="active",
            model_id="gpt-4-turbo",
            tools_config={
                "tools": [
                    {"name": "web_search", "type": "function"},
                    {"name": "calculator", "type": "function"},
                    {"name": "file_reader", "type": "function"},
                ]
            },
            planning=True,
        )

        # Mock agent service
        mock_agent_service = AsyncMock(spec=AgentService)
        mock_agent_service.get.return_value = agent

        # Mock auth context
        auth_context = A2AAuthContext(
            authenticated=True,
            auth_method="bearer",
            user_id="test_user",
            workspace_id="test_workspace",
            permissions=["read", "execute"],
            metadata={},
        )

        # Test handle_agent_card
        response = await handle_agent_card(
            request_id="integration-test",
            params={},
            agent_service=mock_agent_service,
            agent_id=agent.id,
            base_url="https://api.agentarea.com",
            auth_context=auth_context,
        )

        # Verify response
        assert response.jsonrpc == "2.0"
        assert response.id == "integration-test"
        assert response.result is not None

        agent_card = response.result
        assert isinstance(agent_card, AgentCard)

        # Verify current agent data is included
        assert agent_card.name == "Production Agent"
        assert agent_card.description == "A production-ready AI agent"
        assert agent_card.url == f"https://api.agentarea.com/api/v1/agents/{agent.id}/a2a/rpc"

        # Verify capabilities reflect current system capabilities
        assert agent_card.capabilities.streaming is True
        assert agent_card.capabilities.push_notifications is False
        assert agent_card.capabilities.state_transition_history is True

        # Verify skills reflect agent configuration
        assert len(agent_card.skills) == 3  # text-processing, tool-execution, task-planning
        skill_ids = [skill.id for skill in agent_card.skills]
        assert "text-processing" in skill_ids
        assert "tool-execution" in skill_ids  # Because agent has tools
        assert "task-planning" in skill_ids  # Because agent has planning enabled

        # Verify provider information
        assert agent_card.provider.organization == "AgentArea"
        assert agent_card.provider.url == f"https://api.agentarea.com/api/v1/agents/{agent.id}"

    async def test_well_known_endpoint_with_real_agent_data(self):
        """Test well-known endpoint returns current agent data correctly."""
        # Create a minimal agent
        agent = Agent(
            id=uuid4(),
            name="Minimal Agent",
            description="",
            status="active",
            model_id="claude-3-haiku",
            tools_config=None,
            planning=False,
        )

        # Mock agent service
        mock_agent_service = AsyncMock(spec=AgentService)
        mock_agent_service.get.return_value = agent

        # Mock auth context
        auth_context = A2AAuthContext(
            authenticated=False,
            auth_method="none",
            user_id=None,
            workspace_id=None,
            permissions=[],
            metadata={},
        )

        # Mock request
        mock_request = MagicMock(spec=Request)
        mock_request.client.host = "192.168.1.100"
        mock_request.headers.get.return_value = "AgentArea-Client/1.0"

        # Test get_agent_well_known
        agent_card = await get_agent_well_known(
            agent_id=agent.id,
            request=mock_request,
            auth_context=auth_context,
            agent_service=mock_agent_service,
        )

        # Verify response
        assert isinstance(agent_card, AgentCard)

        # Verify current agent data is included
        assert agent_card.name == "Minimal Agent"
        assert "claude-3-haiku" in agent_card.description  # Model info included in description
        assert agent_card.url == f"/api/v1/agents/{agent.id}/a2a/rpc"

        # Verify capabilities
        assert agent_card.capabilities.streaming is True
        assert agent_card.capabilities.push_notifications is False
        assert agent_card.capabilities.state_transition_history is True

        # Verify skills reflect minimal configuration
        assert len(agent_card.skills) == 1  # Only text-processing for minimal agent
        assert agent_card.skills[0].id == "text-processing"

        # Verify provider information
        assert agent_card.provider.organization == "AgentArea"
        assert agent_card.provider.url == f"/api/v1/agents/{agent.id}"

    async def test_agent_discovery_handles_different_statuses(self):
        """Test agent discovery handles different agent statuses correctly."""
        test_cases = [
            ("active", True, ""),
            ("available", True, ""),
            ("ready", True, ""),
            ("maintenance", False, "Status: maintenance"),
            ("disabled", False, "Status: disabled"),
        ]

        for status, should_succeed, expected_status_text in test_cases:
            agent = Agent(
                id=uuid4(),
                name=f"Agent {status}",
                description="Test agent",
                status=status,
                model_id="gpt-3.5-turbo",
                tools_config=None,
                planning=False,
            )

            mock_agent_service = AsyncMock(spec=AgentService)
            mock_agent_service.get.return_value = agent

            auth_context = A2AAuthContext(
                authenticated=True,
                auth_method="bearer",
                user_id="test_user",
                workspace_id="test_workspace",
                permissions=["read", "execute"],
                metadata={},
            )

            response = await handle_agent_card(
                request_id=f"test-{status}",
                params={},
                agent_service=mock_agent_service,
                agent_id=agent.id,
                base_url="https://api.example.com",
                auth_context=auth_context,
            )

            if should_succeed:
                # Should return successful response
                assert response.result is not None
                assert response.error is None
                if expected_status_text:
                    assert expected_status_text in response.result.description
            else:
                # Should return error response
                assert response.result is None
                assert response.error is not None
                assert response.error.code == -32602
                assert "not available" in response.error.message
