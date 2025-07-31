"""Tests for Temporal backbone integration with ADK agents."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any

from ..services.temporal_llm_service import TemporalLlmService, TemporalLlmServiceFactory
from ..services.temporal_tool_service import TemporalTool, TemporalToolFactory
from ..services.adk_service_factory import create_adk_runner
from ..utils.agent_builder import build_temporal_enhanced_agent, create_simple_agent_config


class TestTemporalLlmService:
    """Test Temporal LLM service integration."""
    
    def test_llm_service_creation(self):
        """Test creating Temporal LLM service."""
        agent_config = {"name": "test_agent", "model": "gpt-4"}
        session_data = {"user_id": "test", "session_id": "session1"}
        
        service = TemporalLlmServiceFactory.create_llm_service(
            model="gpt-4",
            agent_config=agent_config,
            session_data=session_data
        )
        
        assert isinstance(service, TemporalLlmService)
        assert service.model == "gpt-4"
        assert service.agent_config == agent_config
        assert service.session_data == session_data
    
    def test_supported_models(self):
        """Test that service supports all models."""
        patterns = TemporalLlmService.supported_models()
        assert len(patterns) > 0
        assert ".*" in patterns  # Should support all models
    
    @patch('temporalio.workflow.execute_activity')
    async def test_generate_content_async(self, mock_execute_activity):
        """Test LLM content generation through Temporal."""
        # Mock activity result
        mock_execute_activity.return_value = {
            "content": "Hello, how can I help you?",
            "role": "assistant",
            "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
            "cost": 0.00036
        }
        
        # Create service
        service = TemporalLlmService(
            model="gpt-4",
            agent_config={"name": "test"},
            session_data={"user_id": "test"}
        )
        
        # Mock LLM request
        from ...ag.adk.models.llm_request import LlmRequest
        from google.genai import types
        
        llm_request = LlmRequest(
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part(text="Hello")]
                )
            ]
        )
        
        # Generate content
        responses = []
        async for response in service.generate_content_async(llm_request):
            responses.append(response)
        
        assert len(responses) == 1
        response = responses[0]
        assert response.content.parts[0].text == "Hello, how can I help you?"
        assert response.usage.total_tokens == 18
        assert response.cost == 0.00036


class TestTemporalToolService:
    """Test Temporal tool service integration."""
    
    def test_temporal_tool_creation(self):
        """Test creating Temporal tool."""
        from google.genai import types
        from uuid import uuid4
        
        server_id = uuid4()
        func_decl = types.FunctionDeclaration(
            name="calculator",
            description="Perform calculations"
        )
        
        tool = TemporalTool(
            name="calculator",
            description="Math tool",
            function_declaration=func_decl,
            server_instance_id=server_id
        )
        
        assert tool.name == "calculator"
        assert tool.description == "Math tool"
        assert tool.server_instance_id == server_id
        assert tool._get_declaration() == func_decl
    
    @patch('temporalio.workflow.execute_activity')
    async def test_tool_execution(self, mock_execute_activity):
        """Test tool execution through Temporal."""
        # Mock activity result
        mock_execute_activity.return_value = {
            "success": True,
            "result": "42"
        }
        
        # Create tool
        tool = TemporalTool(
            name="calculator",
            description="Math tool"
        )
        
        # Mock tool context
        from ...ag.adk.tools.tool_context import ToolContext
        tool_context = MagicMock(spec=ToolContext)
        
        # Execute tool
        result = await tool.run_async(
            args={"expression": "6 * 7"},
            tool_context=tool_context
        )
        
        assert result == "42"
        mock_execute_activity.assert_called_once()
    
    def test_tool_factory_creation(self):
        """Test tool factory functionality."""
        agent_config = {"name": "test_agent"}
        session_data = {"user_id": "test"}
        
        factory = TemporalToolFactory(agent_config, session_data)
        
        # Test creating tool from config
        tool_config = {
            "name": "test_tool",
            "description": "Test tool",
            "parameters": {"type": "object"}
        }
        
        tool = factory.create_tool_from_config(tool_config)
        
        assert isinstance(tool, TemporalTool)
        assert tool.name == "test_tool"
        assert tool.description == "Test tool"


class TestAgentBuilder:
    """Test enhanced agent builder."""
    
    def test_create_simple_agent_config(self):
        """Test creating simple agent configuration."""
        config = create_simple_agent_config(
            name="test_agent",
            model="gpt-4",
            instructions="Test instructions",
            description="Test agent"
        )
        
        assert config["name"] == "test_agent"
        assert config["model"] == "gpt-4"
        assert config["instructions"] == "Test instructions"
        assert config["description"] == "Test agent"
    
    @patch('agentarea_execution.adk_temporal.utils.agent_builder.build_adk_agent_from_config')
    @patch('agentarea_execution.adk_temporal.services.temporal_llm_service.TemporalLlmServiceFactory.register_with_adk')
    def test_build_temporal_enhanced_agent(self, mock_register, mock_build_agent):
        """Test building Temporal-enhanced agent."""
        # Mock ADK agent
        mock_agent = MagicMock()
        mock_agent.name = "test_agent"
        mock_build_agent.return_value = mock_agent
        
        agent_config = {"name": "test_agent", "model": "gpt-4"}
        session_data = {"user_id": "test"}
        
        # Build enhanced agent
        agent = build_temporal_enhanced_agent(agent_config, session_data)
        
        assert agent == mock_agent
        mock_register.assert_called_once()
        mock_build_agent.assert_called_once()


class TestServiceFactory:
    """Test ADK service factory with Temporal backbone."""
    
    @patch('agentarea_execution.adk_temporal.services.adk_service_factory.build_temporal_enhanced_agent')
    @patch('agentarea_execution.adk_temporal.services.adk_service_factory.build_adk_agent_from_config')
    def test_create_adk_runner_with_temporal_backbone(self, mock_build_standard, mock_build_enhanced):
        """Test creating ADK runner with Temporal backbone enabled."""
        # Mock agents
        mock_enhanced_agent = MagicMock()
        mock_enhanced_agent.name = "enhanced_agent"
        mock_build_enhanced.return_value = mock_enhanced_agent
        
        mock_standard_agent = MagicMock()
        mock_standard_agent.name = "standard_agent"
        mock_build_standard.return_value = mock_standard_agent
        
        agent_config = {"name": "test_agent", "model": "gpt-4"}
        session_data = {"user_id": "test", "session_id": "session1", "app_name": "test_app"}
        
        # Test with Temporal backbone enabled
        runner = create_adk_runner(
            agent_config=agent_config,
            session_data=session_data,
            use_temporal_backbone=True
        )
        
        assert runner is not None
        mock_build_enhanced.assert_called_once_with(agent_config, session_data)
        mock_build_standard.assert_not_called()
        
        # Test with Temporal backbone disabled
        mock_build_enhanced.reset_mock()
        runner = create_adk_runner(
            agent_config=agent_config,
            session_data=session_data,
            use_temporal_backbone=False
        )
        
        assert runner is not None
        mock_build_standard.assert_called_once_with(agent_config)
        mock_build_enhanced.assert_not_called()


class TestIntegrationFlow:
    """Test end-to-end integration flow."""
    
    @patch('temporalio.workflow.execute_activity')
    async def test_full_integration_flow(self, mock_execute_activity):
        """Test complete integration from agent creation to execution."""
        # Mock activity results
        mock_execute_activity.side_effect = [
            # LLM call result
            {
                "content": "I'll help you with that calculation.",
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "calculator",
                            "arguments": '{"expression": "15 * 23"}'
                        }
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 15, "total_tokens": 35},
                "cost": 0.0007
            },
            # Tool call result
            {
                "success": True,
                "result": "345"
            },
            # Final LLM call result
            {
                "content": "The result of 15 * 23 is 345.",
                "role": "assistant",
                "usage": {"prompt_tokens": 25, "completion_tokens": 10, "total_tokens": 35},
                "cost": 0.0007
            }
        ]
        
        # This test would require a more complex setup with actual workflow execution
        # For now, we verify that the components can be created and configured correctly
        
        agent_config = create_simple_agent_config(
            name="calculator_agent",
            model="gpt-4",
            instructions="You can perform calculations using the calculator tool.",
            tools=[
                {
                    "name": "calculator",
                    "description": "Perform mathematical calculations",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expression": {"type": "string"}
                        }
                    }
                }
            ]
        )
        
        session_data = {
            "user_id": "test_user",
            "session_id": "test_session",
            "app_name": "test_app"
        }
        
        # Verify we can create the runner with Temporal backbone
        runner = create_adk_runner(
            agent_config=agent_config,
            session_data=session_data,
            use_temporal_backbone=True
        )
        
        assert runner is not None
        assert hasattr(runner, 'agent')
        assert runner.agent.name == "calculator_agent"


if __name__ == "__main__":
    pytest.main([__file__])