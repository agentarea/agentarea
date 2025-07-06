"""
Unit Tests for AgentBuilderService
=================================

Tests individual methods of AgentBuilderService in isolation using mocks.
"""

from datetime import datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from agentarea_agents.application.agent_builder_service import (
    AgentBuilderService,
)
from agentarea_agents.domain.models import Agent
from agentarea_common.events.broker import EventBroker
from agentarea_common.utils.types import sanitize_agent_name
from agentarea_llm.domain.models import ModelInstance


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
    def mock_model_instance_service(self):
        """Mock model instance service"""
        return AsyncMock()

    @pytest.fixture
    def mock_mcp_service(self):
        """Mock MCP server instance service"""
        return AsyncMock()

    @pytest.fixture
    def agent_builder_service(
        self, mock_repository, mock_event_broker, mock_model_instance_service, mock_mcp_service
    ):
        """Create AgentBuilderService with mocked dependencies"""
        return AgentBuilderService(
            repository=mock_repository,
            event_broker=mock_event_broker,
            model_instance_service=mock_model_instance_service,
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
    def sample_model_instance(self):
        """Sample model instance using new architecture"""
        return ModelInstance(
            id=uuid4(),
            provider_config_id=str(uuid4()),
            model_spec_id=str(uuid4()),
            name="Test Model Instance",
            description="Test model instance description",
            is_active=True,
            is_public=True,
        )

    @pytest.mark.asyncio
    async def test_build_agent_config_success(
        self,
        agent_builder_service,
        mock_repository,
        mock_model_instance_service,
        sample_agent,
        sample_model_instance,
    ):
        """Test successful agent configuration building"""
        # Setup mocks
        mock_repository.get.return_value = sample_agent
        mock_model_instance_service.get.return_value = sample_model_instance

        # Execute
        result = await agent_builder_service.build_agent_config(sample_agent.id)

        # Verify
        assert result is not None
        assert result["id"] == str(sample_agent.id)
        assert result["name"] == sanitize_agent_name(sample_agent.name)
        assert result["description"] == sample_agent.description
        assert result["instruction"] == sample_agent.instruction
        assert result["model_instance"] == sample_model_instance
        assert result["planning_enabled"] == sample_agent.planning
        assert result["workflow_type"] == "single"
        assert "tools_config" in result
        assert "metadata" in result

        # Verify repository was called correctly
        mock_repository.get.assert_called_once_with(sample_agent.id)
        mock_model_instance_service.get.assert_called_once_with(UUID(sample_agent.model_id))

    @pytest.mark.asyncio
    async def test_build_agent_config_agent_not_found(self, agent_builder_service, mock_repository):
        """Test building config when agent doesn't exist"""
        # Setup mocks
        mock_repository.get.return_value = None
        agent_id = uuid4()

        # Execute
        result = await agent_builder_service.build_agent_config(agent_id)

        # Verify
        assert result is None
        mock_repository.get.assert_called_once_with(agent_id)

    @pytest.mark.asyncio
    async def test_build_agent_config_model_not_found(
        self, agent_builder_service, mock_repository, mock_model_instance_service, sample_agent
    ):
        """Test building config when model instance doesn't exist"""
        # Setup mocks
        mock_repository.get.return_value = sample_agent
        mock_model_instance_service.get.return_value = None

        # Execute
        result = await agent_builder_service.build_agent_config(sample_agent.id)

        # Verify
        assert result is None
        mock_repository.get.assert_called_once_with(sample_agent.id)
        mock_model_instance_service.get.assert_called_once_with(UUID(sample_agent.model_id))

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
    async def test_build_tools_config_with_builtin_tools(self, agent_builder_service, sample_agent):
        """Test building tools config with builtin tools"""
        # Setup agent with builtin tools
        sample_agent.tools_config = {"builtin_tools": ["calculator", "weather", "web_search"]}

        # Execute
        result = await agent_builder_service._build_tools_config(sample_agent)

        # Verify
        assert result["builtin_tools"] == ["calculator", "weather", "web_search"]
        assert result["mcp_servers"] == []
        assert result["custom_tools"] == []

    @pytest.mark.asyncio
    async def test_validate_agent_config_success(
        self,
        agent_builder_service,
        mock_repository,
        mock_model_instance_service,
        sample_agent,
        sample_model_instance,
    ):
        """Test successful agent validation"""
        # Setup mocks
        mock_repository.get.return_value = sample_agent
        mock_model_instance_service.get.return_value = sample_model_instance

        # Execute
        errors = await agent_builder_service.validate_agent_config(sample_agent.id)

        # Verify
        assert errors == []

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
    async def test_get_agent_capabilities_planning_enabled(
        self,
        agent_builder_service,
        mock_repository,
        mock_model_instance_service,
        sample_agent,
        sample_model_instance,
    ):
        """Test getting capabilities for agent with planning enabled"""
        # Setup agent with planning
        sample_agent.planning = True
        mock_repository.get.return_value = sample_agent
        mock_model_instance_service.get.return_value = sample_model_instance

        # Execute
        result = await agent_builder_service.get_agent_capabilities(sample_agent.id)

        # Verify
        assert result["planning"] == True
        assert result["workflow_type"] == "sequential"
        assert result["streaming"] == True
        assert "tools" in result
        assert "model_provider" in result

    @pytest.mark.asyncio
    async def test_get_agent_capabilities_no_planning(
        self,
        agent_builder_service,
        mock_repository,
        mock_model_instance_service,
        sample_agent,
        sample_model_instance,
    ):
        """Test getting capabilities for agent without planning"""
        # Setup agent without planning
        sample_agent.planning = False
        mock_repository.get.return_value = sample_agent
        mock_model_instance_service.get.return_value = sample_model_instance

        # Execute
        result = await agent_builder_service.get_agent_capabilities(sample_agent.id)

        # Verify
        assert result["planning"] == False
        assert result["workflow_type"] == "single"
        assert result["streaming"] == True

    @pytest.mark.asyncio
    async def test_get_agent_capabilities_agent_not_found(
        self, agent_builder_service, mock_repository
    ):
        """Test getting capabilities when agent doesn't exist"""
        # Setup mocks
        mock_repository.get.return_value = None
        agent_id = uuid4()

        # Execute
        result = await agent_builder_service.get_agent_capabilities(agent_id)

        # Verify
        assert result == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
