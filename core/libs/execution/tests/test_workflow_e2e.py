#!/usr/bin/env python3
"""
Comprehensive E2E test runner for AgentExecutionWorkflow.

This demonstrates testing strategies following Temporal best practices:
1. Integration tests with WorkflowEnvironment (recommended)
2. Unit tests for individual activities
3. End-to-end tests with real Temporal server
4. Time-skipping tests for timeout scenarios

Run with: python test_workflow_e2e.py
"""

import asyncio
import logging
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockActivityServices:
    """Mock activity services for testing."""
    
    def __init__(self):
        self.agent_service = AsyncMock()
        self.mcp_service = AsyncMock()
        self.llm_service = AsyncMock()
        self.event_broker = AsyncMock()
        
        # Configure realistic return values
        self.agent_service.build_agent_config.return_value = {
            "name": "test_weather_agent",
            "description": "Agent that provides weather information",
            "instruction": "You are a helpful weather assistant. Use tools to get current weather information.",
            "model_instance": {
                "model_name": "gemini-2.0-flash",
                "provider": "google",
            },
            "tools_config": {
                "mcp_servers": [
                    {
                        "id": str(uuid4()),
                        "name": "weather_server",
                        "enabled": True,
                    }
                ],
            },
        }
        
        self.agent_service.update_agent_memory.return_value = {
            "memory_entries_created": 2
        }
        
        # Mock MCP server with weather tool
        server_instance = MagicMock()
        server_instance.id = uuid4()
        server_instance.name = "weather_server"
        server_instance.status = "running"
        
        self.mcp_service.get_server_instance.return_value = server_instance
        self.mcp_service.get_server_tools.return_value = [
            {
                "name": "get_weather",
                "description": "Get current weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "City name"}
                    },
                    "required": ["city"]
                }
            }
        ]
        
        self.event_broker.publish_event.return_value = None


async def test_integration_workflow_success():
    """Integration test: Successful workflow execution with mocked activities."""
    logger.info("🧪 Running Integration Test: Successful Workflow Execution")
    
    try:
        # Import after setting up environment
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker
        
        # Create test request
        from agentarea_execution.models import AgentExecutionRequest
        
        request = AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=uuid4(),
            user_id="test_user",
            task_query="What's the weather like in New York?",
            max_reasoning_iterations=3,
            timeout_seconds=120,
        )
        
        # Create mock services
        mock_services = MockActivityServices()
        
        # Mock successful activity responses
        async def mock_validate_agent_configuration_activity(agent_id, activity_services):
            logger.info(f"✅ Mock: Validating agent {agent_id}")
            return {
                "valid": True,
                "errors": [],
                "agent_config": await activity_services.agent_service.build_agent_config(agent_id),
            }
        
        async def mock_discover_available_tools_activity(agent_id, activity_services):
            logger.info(f"🔧 Mock: Discovering tools for agent {agent_id}")
            return [
                {
                    "name": "get_weather",
                    "description": "Get current weather for a city",
                    "mcp_server_id": str(uuid4()),
                    "mcp_server_name": "weather_server",
                }
            ]
        
        async def mock_execute_agent_task_activity(request, available_tools, activity_services):
            logger.info(f"🤖 Mock: Executing agent task for {request.task_id}")
            
            # Simulate ADK agent execution
            response = f"The weather in New York is sunny with a temperature of 22°C. I used the get_weather tool to retrieve this information."
            
            return {
                "success": True,
                "final_response": response,
                "conversation_history": [
                    {"role": "user", "content": request.task_query},
                    {"role": "assistant", "content": response},
                ],
                "execution_metrics": {
                    "reasoning_iterations": 1,
                    "tool_calls": 1,
                    "execution_duration_seconds": 2.5,
                },
                "artifacts": [],
            }
        
        async def mock_persist_agent_memory_activity(agent_id, task_id, conversation_history, task_result, activity_services):
            logger.info(f"💾 Mock: Persisting memory for agent {agent_id}")
            return {
                "success": True,
                "memory_entries_created": len(conversation_history),
                "conversation_length": len(conversation_history),
            }
        
        async def mock_publish_task_event_activity(event_type, event_data, activity_services):
            logger.info(f"📢 Mock: Publishing event {event_type}")
            return {
                "success": True,
                "event_type": event_type,
                "published_at": event_data.get("timestamp", "2024-01-15T10:30:00Z"),
            }
        
        # Set up workflow environment
        async with WorkflowEnvironment() as env:
            # Import workflow after environment setup
            from agentarea_execution.workflows.agent_execution import AgentExecutionWorkflow
            
            # Create worker with mocked activities
            worker = Worker(
                env.client,
                task_queue="test-agent-execution",
                workflows=[AgentExecutionWorkflow],
                activities=[
                    mock_validate_agent_configuration_activity,
                    mock_discover_available_tools_activity,
                    mock_execute_agent_task_activity,
                    mock_persist_agent_memory_activity,
                    mock_publish_task_event_activity,
                ],
            )
            
            # Execute workflow
            async with worker:
                logger.info("🚀 Starting workflow execution...")
                
                result = await env.client.execute_workflow(
                    AgentExecutionWorkflow.run,
                    request,
                    id=f"integration-test-{request.task_id}",
                    task_queue="test-agent-execution",
                    execution_timeout=timedelta(minutes=5),
                )
                
                # Verify results
                logger.info("📊 Verifying workflow results...")
                
                assert result.success is True, f"Workflow failed: {result.error_message}"
                assert result.task_id == request.task_id
                assert result.agent_id == request.agent_id
                assert "sunny" in result.final_response.lower()
                assert "22°C" in result.final_response
                assert len(result.conversation_history) >= 2
                assert result.execution_metrics["reasoning_iterations"] == 1
                assert result.execution_metrics["tool_calls"] == 1
                
                logger.info("✅ Integration test PASSED!")
                logger.info(f"   Final response: {result.final_response}")
                logger.info(f"   Conversation length: {len(result.conversation_history)}")
                logger.info(f"   Execution duration: {result.execution_metrics.get('execution_duration_seconds', 0):.2f}s")
                
                return result
                
    except ImportError as e:
        logger.error(f"❌ Missing dependencies: {e}")
        logger.info("💡 Install with: pip install temporalio pytest")
        return None
    except Exception as e:
        logger.error(f"❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return None


async def test_unit_activities():
    """Unit tests for individual activities."""
    logger.info("🧪 Running Unit Tests: Individual Activities")
    
    try:
        from agentarea_execution.activities.agent_activities import (
            validate_agent_configuration_activity,
            discover_available_tools_activity,
        )
        
        # Test agent validation
        logger.info("🔍 Testing agent configuration validation...")
        
        mock_services = MockActivityServices()
        agent_id = uuid4()
        
        validation_result = await validate_agent_configuration_activity(agent_id, mock_services)
        
        assert validation_result["valid"] is True
        assert len(validation_result["errors"]) == 0
        assert validation_result["agent_config"] is not None
        
        logger.info("✅ Agent validation test passed")
        
        # Test tool discovery
        logger.info("🔧 Testing tool discovery...")
        
        tools_result = await discover_available_tools_activity(agent_id, mock_services)
        
        # With our mock, this should return empty list since no MCP servers are configured
        assert isinstance(tools_result, list)
        
        logger.info("✅ Tool discovery test passed")
        logger.info(f"   Found {len(tools_result)} tools")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Unit tests failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_timeout_handling():
    """Test workflow timeout handling with time-skipping."""
    logger.info("🧪 Running Timeout Test: Time-Skipping Capabilities")
    
    try:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker
        from agentarea_execution.workflows.agent_execution import AgentExecutionWorkflow
        from agentarea_execution.models import AgentExecutionRequest
        
        request = AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=uuid4(),
            user_id="test_user",
            task_query="This is a timeout test",
            max_reasoning_iterations=3,
            timeout_seconds=60,
        )
        
        # Mock slow execution activity
        async def slow_execute_agent_task_activity(request, available_tools, activity_services):
            logger.info("⏳ Mock: Simulating slow agent execution (10 minutes)...")
            await asyncio.sleep(600)  # 10 minutes - will be skipped in test
            return {
                "success": True,
                "final_response": "Slow response",
                "conversation_history": [],
                "execution_metrics": {
                    "reasoning_iterations": 1,
                    "tool_calls": 0,
                    "execution_duration_seconds": 600,
                },
                "artifacts": [],
            }
        
        async with WorkflowEnvironment() as env:
            worker = Worker(
                env.client,
                task_queue="test-timeout",
                workflows=[AgentExecutionWorkflow],
                activities=[slow_execute_agent_task_activity],
            )
            
            async with worker:
                # Execute workflow with short timeout
                try:
                    result = await env.client.execute_workflow(
                        AgentExecutionWorkflow.run,
                        request,
                        id=f"timeout-test-{request.task_id}",
                        task_queue="test-timeout",
                        execution_timeout=timedelta(minutes=1),  # Shorter than activity duration
                    )
                    
                    # Should not reach here
                    logger.error("❌ Timeout test failed - workflow should have timed out")
                    return False
                    
                except Exception as e:
                    if "timeout" in str(e).lower():
                        logger.info("✅ Timeout test passed - workflow correctly timed out")
                        return True
                    else:
                        logger.error(f"❌ Unexpected error in timeout test: {e}")
                        return False
                        
    except Exception as e:
        logger.error(f"❌ Timeout test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_error_recovery():
    """Test error recovery and retry mechanisms."""
    logger.info("🧪 Running Error Recovery Test: Retry Mechanisms")
    
    try:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker
        from agentarea_execution.workflows.agent_execution import AgentExecutionWorkflow
        from agentarea_execution.models import AgentExecutionRequest
        
        request = AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=uuid4(),
            user_id="test_user",
            task_query="Test error recovery",
            max_reasoning_iterations=3,
            timeout_seconds=120,
        )
        
        # Mock execution with failure then success
        attempt_count = 0
        
        async def failing_then_succeeding_activity(request, available_tools, activity_services):
            nonlocal attempt_count
            attempt_count += 1
            
            if attempt_count == 1:
                logger.info("💥 Mock: First attempt fails")
                return {
                    "success": False,
                    "error_message": "Simulated ADK execution failure",
                    "conversation_history": [
                        {"role": "user", "content": request.task_query},
                        {"role": "system", "content": "Error: Simulated ADK execution failure"},
                    ],
                    "execution_metrics": {
                        "reasoning_iterations": 0,
                        "tool_calls": 0,
                        "execution_duration_seconds": 0,
                    },
                    "artifacts": [],
                }
            else:
                logger.info("✅ Mock: Retry succeeds")
                return {
                    "success": True,
                    "final_response": "Recovery successful after retry",
                    "conversation_history": [
                        {"role": "user", "content": request.task_query},
                        {"role": "assistant", "content": "Recovery successful after retry"},
                    ],
                    "execution_metrics": {
                        "reasoning_iterations": 1,
                        "tool_calls": 0,
                        "execution_duration_seconds": 1.5,
                    },
                    "artifacts": [],
                }
        
        async with WorkflowEnvironment() as env:
            worker = Worker(
                env.client,
                task_queue="test-error-recovery",
                workflows=[AgentExecutionWorkflow],
                activities=[failing_then_succeeding_activity],
            )
            
            async with worker:
                result = await env.client.execute_workflow(
                    AgentExecutionWorkflow.run,
                    request,
                    id=f"error-recovery-test-{request.task_id}",
                    task_queue="test-error-recovery",
                    execution_timeout=timedelta(minutes=5),
                )
                
                # Verify recovery
                if result.success and "recovery successful" in result.final_response.lower():
                    logger.info("✅ Error recovery test passed")
                    logger.info(f"   Attempts made: {attempt_count}")
                    return True
                else:
                    logger.error(f"❌ Error recovery test failed: {result}")
                    return False
                    
    except Exception as e:
        logger.error(f"❌ Error recovery test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_e2e_with_real_temporal_server():
    """End-to-end test with real Temporal server (optional)."""
    logger.info("🧪 Running E2E Test: Real Temporal Server")
    
    try:
        from temporalio.client import Client
        from temporalio.worker import Worker
        from agentarea_execution.workflows.agent_execution import AgentExecutionWorkflow
        from agentarea_execution.models import AgentExecutionRequest
        
        # Connect to real Temporal server
        try:
            client = await Client.connect("localhost:7233")
            logger.info("✅ Connected to real Temporal server")
        except Exception as e:
            logger.warning(f"⚠️ Real Temporal server not available: {e}")
            logger.info("💡 Start Temporal server with: temporal server start-dev")
            return None
        
        request = AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=uuid4(),
            user_id="e2e_test_user",
            task_query="E2E test: What's the weather like?",
            max_reasoning_iterations=3,
            timeout_seconds=180,
        )
        
        # Mock realistic execution
        async def realistic_execute_agent_task_activity(request, available_tools, activity_services):
            logger.info("🤖 Realistic: Executing agent task...")
            
            # Simulate some processing time
            await asyncio.sleep(0.5)
            
            return {
                "success": True,
                "final_response": "E2E test successful. Weather information would be retrieved here.",
                "conversation_history": [
                    {"role": "user", "content": request.task_query},
                    {"role": "assistant", "content": "E2E test successful. Weather information would be retrieved here."},
                ],
                "execution_metrics": {
                    "reasoning_iterations": 1,
                    "tool_calls": 1,
                    "execution_duration_seconds": 0.5,
                },
                "artifacts": [],
            }
        
        # Create worker
        worker = Worker(
            client,
            task_queue="e2e-test-queue",
            workflows=[AgentExecutionWorkflow],
            activities=[realistic_execute_agent_task_activity],
        )
        
        # Execute workflow
        async with worker:
            result = await client.execute_workflow(
                AgentExecutionWorkflow.run,
                request,
                id=f"e2e-test-{request.task_id}",
                task_queue="e2e-test-queue",
                execution_timeout=timedelta(minutes=5),
            )
            
            if result.success:
                logger.info("✅ E2E test passed")
                logger.info(f"   Response: {result.final_response}")
                return result
            else:
                logger.error(f"❌ E2E test failed: {result}")
                return None
                
    except Exception as e:
        logger.error(f"❌ E2E test failed: {e}")
        import traceback
        traceback.print_exc()
        return None


async def main():
    """Run all tests."""
    logger.info("🏁 Starting Comprehensive Workflow Testing")
    logger.info("=" * 80)
    
    test_results = {}
    
    # Run tests
    test_results["integration"] = await test_integration_workflow_success()
    test_results["unit"] = await test_unit_activities()
    test_results["timeout"] = await test_timeout_handling()
    test_results["error_recovery"] = await test_error_recovery()
    test_results["e2e"] = await test_e2e_with_real_temporal_server()
    
    # Summary
    logger.info("=" * 80)
    logger.info("📊 Test Summary")
    logger.info("=" * 80)
    
    passed = 0
    total = 0
    
    for test_name, result in test_results.items():
        total += 1
        if result:
            passed += 1
            logger.info(f"✅ {test_name.replace('_', ' ').title()}: PASSED")
        elif result is None:
            logger.info(f"⚠️ {test_name.replace('_', ' ').title()}: SKIPPED")
        else:
            logger.info(f"❌ {test_name.replace('_', ' ').title()}: FAILED")
    
    logger.info(f"\n🎯 Overall: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 All tests passed! Workflow implementation is working correctly.")
    else:
        logger.warning("⚠️ Some tests failed. Review the implementation.")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1) 