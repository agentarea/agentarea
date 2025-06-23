"""
Unit Tests for AgentBuilderService
=================================

Tests individual methods of AgentBuilderService in isolation using mocks.
"""

from datetime import datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from agentarea.common.events.broker import EventBroker
from agentarea.modules.agents.application.agent_builder_service import (
    AgentBuilderService,
)
from agentarea.modules.agents.domain.models import Agent
from agentarea.modules.llm.domain.models import LLMModelInstance


class TestAgentBuilderService:
    """Unit tests for AgentBuilderService"""

    @pytest.fixture
    def mock_repository(self):
        """Mock agent repository"""
        return AsyncMock()

    @pytest.fixture
    def mock_event_broker(self):
        """Mock event broker"""
        return AsyncMock(spec=EventBroker)

    @pytest.fixture
    def mock_llm_service(self):
        """Mock LLM model instance service"""
        return AsyncMock()

    @pytest.fixture
    def mock_mcp_service(self):
        """Mock MCP server instance service"""
        return AsyncMock()

    @pytest.fixture
    def agent_builder_service(
        self, mock_repository, mock_event_broker, mock_llm_service, mock_mcp_service
    ):
        """Create AgentBuilderService with mocked dependencies"""
        return AgentBuilderService(
            repository=mock_repository,
            event_broker=mock_event_broker,
            llm_model_instance_service=mock_llm_service,
            mcp_server_instance_service=mock_mcp_service,
        )

    @pytest.fixture
    def sample_agent(self):
        """Sample agent for testing"""
        agent_id = uuid4()
        model_id = str(uuid4())
        return Agent(
            id=agent_id,
            name="Test Agent",
            description="A test agent",
            instruction="You are a helpful test assistant",
            model_id=model_id,
            tools_config={
                "mcp_server_configs": [],
                "builtin_tools": ["calculator"],
                "custom_tools": [],
            },
            events_config={},
            planning=False,
            status="active",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    @pytest.fixture
    def sample_llm_instance(self):
        """Sample LLM model instance"""
        return LLMModelInstance(
            id=uuid4(),
            name="Test Model",
            provider_id=uuid4(),
            model_id=uuid4(),
            config={"temperature": 0.7},
            status="active",
        )

    async def test_build_agent_config_success(
        self,
        agent_builder_service,
        mock_repository,
        mock_llm_service,
        sample_agent,
        sample_llm_instance,
    ):
        """Test successful agent configuration building"""
        # Setup mocks
        mock_repository.get.return_value = sample_agent
        mock_llm_service.get.return_value = sample_llm_instance

        # Execute
        result = await agent_builder_service.build_agent_config(sample_agent.id)

        # Verify
        assert result is not None
        assert result["id"] == str(sample_agent.id)
        assert result["name"] == sample_agent.name
        assert result["description"] == sample_agent.description
        assert result["instruction"] == sample_agent.instruction
        assert result["model_instance"] == sample_llm_instance
        assert result["planning_enabled"] == sample_agent.planning
        assert result["workflow_type"] == "single"
        assert "tools_config" in result
        assert "metadata" in result

        # Verify repository was called correctly
        mock_repository.get.assert_called_once_with(sample_agent.id)
        mock_llm_service.get.assert_called_once_with(UUID(sample_agent.model_id))

    async def test_build_agent_config_agent_not_found(
        self, agent_builder_service, mock_repository
    ):
        """Test building config when agent doesn't exist"""
        # Setup mocks
        mock_repository.get.return_value = None
        agent_id = uuid4()

        # Execute
        result = await agent_builder_service.build_agent_config(agent_id)

        # Verify
        assert result is None
        mock_repository.get.assert_called_once_with(agent_id)

    async def test_build_agent_config_model_not_found(
        self, agent_builder_service, mock_repository, mock_llm_service, sample_agent
    ):
        """Test building config when LLM model instance doesn't exist"""
        # Setup mocks
        mock_repository.get.return_value = sample_agent
        mock_llm_service.get.return_value = None

        # Execute
        result = await agent_builder_service.build_agent_config(sample_agent.id)

        # Verify
        assert result is None
        mock_repository.get.assert_called_once_with(sample_agent.id)
        mock_llm_service.get.assert_called_once_with(UUID(sample_agent.model_id))

    async def test_build_tools_config_empty(self, agent_builder_service, sample_agent):
        """Test building tools config with empty configuration"""
        # Remove tools config
        agent_without_tools = sample_agent
        agent_without_tools.tools_config = None

        # Execute
        result = await agent_builder_service._build_tools_config(agent_without_tools)

        # Verify
        expected = {"mcp_servers": [], "builtin_tools": [], "custom_tools": []}
        assert result == expected

    async def test_build_tools_config_with_builtin_tools(
        self, agent_builder_service, sample_agent
    ):
        """Test building tools config with builtin tools"""
        # Setup agent with builtin tools
        sample_agent.tools_config = {
            "builtin_tools": ["calculator", "weather", "web_search"]
        }

        # Execute
        result = await agent_builder_service._build_tools_config(sample_agent)

        # Verify
        assert result["builtin_tools"] == ["calculator", "weather", "web_search"]
        assert result["mcp_servers"] == []
        assert result["custom_tools"] == []

    async def test_validate_agent_config_success(
        self,
        agent_builder_service,
        mock_repository,
        mock_llm_service,
        sample_agent,
        sample_llm_instance,
    ):
        """Test successful agent validation"""
        # Setup mocks
        mock_repository.get.return_value = sample_agent
        mock_llm_service.get.return_value = sample_llm_instance

        # Execute
        errors = await agent_builder_service.validate_agent_config(sample_agent.id)

        # Verify
        assert errors == []

    async def test_validate_agent_config_missing_fields(
        self, agent_builder_service, mock_repository, sample_agent
    ):
        """Test validation with missing required fields"""
        # Setup agent with missing fields
        invalid_agent = sample_agent
        invalid_agent.name = ""
        invalid_agent.instruction = ""
        invalid_agent.model_id = ""

        mock_repository.get.return_value = invalid_agent

        # Execute
        errors = await agent_builder_service.validate_agent_config(sample_agent.id)

        # Verify
        assert len(errors) == 3
        assert "Agent name is required" in errors
        assert "Agent instruction is required" in errors
        assert "Agent model_id is required" in errors

    async def test_get_agent_capabilities_planning_enabled(
        self,
        agent_builder_service,
        mock_repository,
        mock_llm_service,
        sample_agent,
        sample_llm_instance,
    ):
        """Test getting capabilities for agent with planning enabled"""
        # Setup agent with planning
        sample_agent.planning = True
        mock_repository.get.return_value = sample_agent
        mock_llm_service.get.return_value = sample_llm_instance

        # Execute
        capabilities = await agent_builder_service.get_agent_capabilities(
            sample_agent.id
        )

        # Verify
        assert capabilities["streaming"] is True
        assert capabilities["planning"] is True
        assert capabilities["workflow_type"] == "sequential"
        assert capabilities["supports_multi_agent"] is True
        assert capabilities["supports_workflows"] is True
        assert capabilities["supports_delegation"] is True
        assert "tools" in capabilities
        assert "events" in capabilities

    async def test_get_agent_capabilities_no_planning(
        self,
        agent_builder_service,
        mock_repository,
        mock_llm_service,
        sample_agent,
        sample_llm_instance,
    ):
        """Test getting capabilities for agent without planning"""
        # Setup agent without planning
        sample_agent.planning = False
        mock_repository.get.return_value = sample_agent
        mock_llm_service.get.return_value = sample_llm_instance

        # Execute
        capabilities = await agent_builder_service.get_agent_capabilities(
            sample_agent.id
        )

        # Verify
        assert capabilities["streaming"] is True
        assert capabilities["planning"] is False
        assert capabilities["workflow_type"] == "single"

    async def test_get_agent_capabilities_agent_not_found(
        self, agent_builder_service, mock_repository
    ):
        """Test getting capabilities when agent doesn't exist"""
        # Setup
        mock_repository.get.return_value = None
        agent_id = uuid4()

        # Execute
        capabilities = await agent_builder_service.get_agent_capabilities(agent_id)

        # Verify
        assert capabilities == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
