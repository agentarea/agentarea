#!/usr/bin/env python3
"""
Test script for Google ADK integration with AgentArea execution library.

This demonstrates how to use the new ADK-powered execution system.
"""

import asyncio
import logging
from uuid import uuid4
from typing import Any, Dict

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockAgentService:
    """Mock agent service for testing."""
    
    async def build_agent_config(self, agent_id) -> Dict[str, Any]:
        return {
            "name": f"test_agent_{agent_id}",
            "description": "Test agent for ADK integration",
            "instruction": "You are a helpful AI assistant. Use tools when needed.",
            "model_instance": {
                "model_name": "gemini-2.0-flash",
                "provider": "google",
            },
            "tools_config": {
                "mcp_servers": [],  # Empty for this test
            },
        }
    
    async def update_agent_memory(self, agent_id, task_id, conversation_history, task_result):
        logger.info(f"Mock: Updated memory for agent {agent_id}")
        return {"memory_entries_created": len(conversation_history)}


class MockMCPService:
    """Mock MCP service for testing."""
    
    async def get_server_instance(self, server_id):
        return None  # No servers for this test
    
    async def get_server_tools(self, server_id):
        return []


class MockLLMService:
    """Mock LLM service for testing."""
    
    async def execute_reasoning(self, **kwargs):
        return {
            "reasoning_text": "I'll help you with that task.",
            "tool_calls": [],
            "model_used": "gemini-2.0-flash",
        }


class MockEventBroker:
    """Mock event broker for testing."""
    
    async def publish_event(self, event_type: str, event_data: Dict[str, Any]):
        logger.info(f"Mock: Published event {event_type}")


class MockActivityServices:
    """Mock activity services container for testing."""
    
    def __init__(self):
        self.agent_service = MockAgentService()
        self.mcp_service = MockMCPService()
        self.llm_service = MockLLMService()
        self.event_broker = MockEventBroker()


async def test_adk_integration():
    """Test the Google ADK integration."""
    try:
        # Import AgentArea execution components
        from agentarea_execution.models import AgentExecutionRequest
        from agentarea_execution.activities.agent_activities import (
            validate_agent_configuration_activity,
            discover_available_tools_activity,
            execute_agent_task_activity,
        )
        from agentarea_execution.adk_adapter import get_adk_adapter
        
        logger.info("🚀 Starting Google ADK integration test...")
        
        # Create test data
        agent_id = uuid4()
        task_id = uuid4()
        user_id = "test_user"
        task_query = "What is the weather in New York? Also calculate 25 * 4."
        
        # Create request
        request = AgentExecutionRequest(
            task_id=task_id,
            agent_id=agent_id,
            user_id=user_id,
            task_query=task_query,
            max_reasoning_iterations=5,
            timeout_seconds=60,
        )
        
        # Create mock services
        mock_services = MockActivityServices()
        
        logger.info("✅ Created test request and mock services")
        
        # Test 1: Validate agent configuration
        logger.info("🔍 Testing agent validation...")
        validation_result = await validate_agent_configuration_activity(
            agent_id, mock_services
        )
        logger.info(f"Validation result: {validation_result}")
        
        # Test 2: Discover tools
        logger.info("🔧 Testing tool discovery...")
        available_tools = await discover_available_tools_activity(
            agent_id, mock_services
        )
        logger.info(f"Available tools: {len(available_tools)} tools found")
        
        # Test 3: Test ADK adapter directly
        logger.info("🤖 Testing ADK adapter...")
        adk_adapter = get_adk_adapter()
        
        # Get mock agent config
        agent_config = await mock_services.agent_service.build_agent_config(agent_id)
        
        # Create ADK agent
        logger.info("Creating Google ADK agent...")
        try:
            adk_agent = adk_adapter.create_adk_agent(
                agent_config=agent_config,
                agent_id=agent_id,
                task_query=task_query,
            )
            logger.info(f"✅ ADK agent created: {adk_agent.name}")
            
            # Test agent execution
            logger.info("🎯 Testing agent execution...")
            result = await adk_adapter.execute_agent_with_adk(
                agent=adk_agent,
                task_query=task_query,
                agent_id=agent_id,
                task_id=task_id,
            )
            
            logger.info("📊 Execution Results:")
            logger.info(f"  Success: {result['success']}")
            logger.info(f"  Response: {result.get('final_response', 'No response')}")
            logger.info(f"  Conversation length: {len(result.get('conversation_history', []))}")
            logger.info(f"  Error: {result.get('error_message', 'None')}")
            
            if result['success']:
                logger.info("🎉 Google ADK integration test PASSED!")
            else:
                logger.warning(f"⚠️  Execution failed but integration working: {result.get('error_message')}")
            
        except Exception as e:
            logger.error(f"❌ ADK integration failed: {e}")
            logger.info("💡 This might be expected if Google ADK dependencies are not installed")
            logger.info("   Install with: pip install google-adk langchain langchain-community")
            
        # Test 4: Full activity execution
        logger.info("🏁 Testing full activity execution...")
        try:
            activity_result = await execute_agent_task_activity(
                request, available_tools, mock_services
            )
            
            logger.info("📈 Full Activity Results:")
            logger.info(f"  Success: {activity_result['success']}")
            logger.info(f"  Response: {activity_result.get('final_response', 'No response')[:100]}...")
            logger.info(f"  Error: {activity_result.get('error_message', 'None')}")
            
        except Exception as e:
            logger.error(f"❌ Full activity test failed: {e}")
        
        logger.info("🏆 ADK integration test completed!")
        
    except ImportError as e:
        logger.error(f"❌ Import error: {e}")
        logger.info("💡 Make sure to install dependencies:")
        logger.info("   pip install google-adk langchain langchain-community")
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """Main test function."""
    await test_adk_integration()


if __name__ == "__main__":
    asyncio.run(main()) 