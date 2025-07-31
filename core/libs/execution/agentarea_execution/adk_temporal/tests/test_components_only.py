"""Test individual components without importing the full workflow module."""

import asyncio
import logging
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

# Add the execution path to sys.path to avoid import issues
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_temporal_llm_service_basic():
    """Test basic TemporalLlmService functionality."""
    logger.info("Testing TemporalLlmService basic functionality...")
    
    try:
        # Import the service directly
        from agentarea_execution.adk_temporal.services.temporal_llm_service import (
            TemporalLlmService, TemporalLlmServiceFactory
        )
        
        agent_config = {"name": "test_agent", "model": "gpt-4"}
        session_data = {"user_id": "test", "session_id": "test_session"}
        
        # Test service creation
        service = TemporalLlmServiceFactory.create_llm_service(
            model="gpt-4",
            agent_config=agent_config,
            session_data=session_data
        )
        
        assert isinstance(service, TemporalLlmService)
        assert service.model == "gpt-4"
        assert service.agent_config == agent_config
        assert service.session_data == session_data
        
        # Test supported models
        patterns = TemporalLlmService.supported_models()
        assert len(patterns) > 0
        assert ".*" in patterns  # Should support all models
        
        logger.info("✅ TemporalLlmService basic test passed")
        return True
        
    except Exception as e:
        logger.error(f"❌ TemporalLlmService basic test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_temporal_tool_service_basic():
    """Test basic TemporalTool functionality."""
    logger.info("Testing TemporalTool basic functionality...")
    
    try:
        from agentarea_execution.adk_temporal.services.temporal_tool_service import (
            TemporalTool, TemporalToolFactory
        )
        
        agent_config = {"name": "test_agent"}
        session_data = {"user_id": "test", "session_id": "test_session"}
        
        # Test tool factory creation
        factory = TemporalToolFactory(agent_config, session_data)
        assert factory.agent_config == agent_config
        assert factory.session_data == session_data
        
        # Test tool creation from config
        tool_config = {
            "name": "test_tool",
            "description": "Test tool for integration",
            "parameters": {"type": "object"}
        }
        
        tool = factory.create_tool_from_config(tool_config)
        
        assert isinstance(tool, TemporalTool)
        assert tool.name == "test_tool"
        assert tool.description == "Test tool for integration"
        
        logger.info("✅ TemporalTool basic test passed")
        return True
        
    except Exception as e:
        logger.error(f"❌ TemporalTool basic test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_agent_builder_basic():
    """Test basic agent builder functionality."""
    logger.info("Testing agent builder basic functionality...")
    
    try:
        from agentarea_execution.adk_temporal.utils.agent_builder import (
            create_simple_agent_config, validate_agent_config
        )
        
        # Test config creation
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
        
        # Test config validation
        assert validate_agent_config(config) is True
        
        # Test invalid config
        invalid_config = {"model": "gpt-4"}  # Missing name
        assert validate_agent_config(invalid_config) is False
        
        logger.info("✅ Agent builder basic test passed")
        return True
        
    except Exception as e:
        logger.error(f"❌ Agent builder basic test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_service_factory_basic():
    """Test basic service factory functionality."""
    logger.info("Testing service factory basic functionality...")
    
    try:
        from agentarea_execution.adk_temporal.services.adk_service_factory import (
            create_default_session_data, validate_runner_config
        )
        
        # Test session data creation
        session_data = create_default_session_data(
            user_id="test_user",
            app_name="test_app"
        )
        
        assert session_data["user_id"] == "test_user"
        assert session_data["app_name"] == "test_app"
        assert "session_id" in session_data
        assert "created_time" in session_data
        
        # Test config validation
        agent_config = {"name": "test_agent", "model": "gpt-4"}
        
        assert validate_runner_config(agent_config, session_data) is True
        
        # Test invalid configs
        assert validate_runner_config({}, session_data) is False  # Missing name
        assert validate_runner_config(agent_config, {}) is False  # Missing session fields
        
        logger.info("✅ Service factory basic test passed")
        return True
        
    except Exception as e:
        logger.error(f"❌ Service factory basic test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_llm_service_with_mock_activity():
    """Test LLM service with mocked Temporal activity."""
    logger.info("Testing LLM service with mocked activity...")
    
    try:
        # Mock the workflow.execute_activity function
        with patch('temporalio.workflow.execute_activity') as mock_execute:
            # Configure mock to return test data
            mock_execute.return_value = {
                "content": "Test response from mocked activity",
                "role": "assistant",
                "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
                "cost": 0.0005
            }
            
            from agentarea_execution.adk_temporal.services.temporal_llm_service import TemporalLlmService
            
            service = TemporalLlmService(
                model="gpt-4",
                agent_config={"name": "test"},
                session_data={"user_id": "test"}
            )
            
            # Create a mock LLM request
            class MockLlmRequest:
                def __init__(self):
                    self.contents = []
                    self.system_instruction = None
                    self.tools = None
            
            llm_request = MockLlmRequest()
            
            # Test message conversion
            messages = service._convert_llm_request_to_messages(llm_request)
            assert isinstance(messages, list)
            
            # Test tools extraction
            tools = service._extract_tools_from_request(llm_request)
            assert tools is None  # No tools in mock request
            
            logger.info("✅ LLM service mock activity test passed")
            return True
            
    except Exception as e:
        logger.error(f"❌ LLM service mock activity test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_integration_without_adk():
    """Test integration components without full ADK dependencies."""
    logger.info("Testing integration without full ADK...")
    
    try:
        # Test that we can import and create basic components
        from agentarea_execution.adk_temporal.services.temporal_llm_service import TemporalLlmServiceFactory
        from agentarea_execution.adk_temporal.services.temporal_tool_service import TemporalToolFactory
        from agentarea_execution.adk_temporal.utils.agent_builder import create_simple_agent_config
        
        # Create test data
        agent_config = create_simple_agent_config(
            name="integration_test_agent",
            model="gpt-4",
            instructions="Integration test agent"
        )
        
        session_data = {
            "user_id": "integration_user",
            "session_id": "integration_session",
            "app_name": "integration_test"
        }
        
        # Create services
        llm_service = TemporalLlmServiceFactory.create_llm_service(
            model="gpt-4",
            agent_config=agent_config,
            session_data=session_data
        )
        
        tool_factory = TemporalToolFactory(agent_config, session_data)
        
        # Verify they were created successfully
        assert llm_service is not None
        assert tool_factory is not None
        
        logger.info("✅ Integration without ADK test passed")
        return True
        
    except Exception as e:
        logger.error(f"❌ Integration without ADK test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all component tests."""
    logger.info("🚀 Starting Temporal backbone component tests...")
    
    tests = [
        test_temporal_llm_service_basic,
        test_temporal_tool_service_basic,
        test_agent_builder_basic,
        test_service_factory_basic,
        test_llm_service_with_mock_activity,
        test_integration_without_adk,
    ]
    
    results = []
    for test in tests:
        try:
            result = await test()
            results.append(result)
        except Exception as e:
            logger.error(f"Test {test.__name__} crashed: {e}")
            results.append(False)
    
    passed = sum(results)
    total = len(results)
    
    logger.info(f"\n📊 Component Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 All component tests passed! Basic Temporal backbone components are working.")
    else:
        logger.warning(f"⚠️ {total - passed} tests failed. Check logs above for details.")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)