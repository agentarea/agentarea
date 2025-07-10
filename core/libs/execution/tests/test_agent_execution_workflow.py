"""
Comprehensive tests for AgentExecutionWorkflow following Temporal testing best practices.

Test Types:
- Unit tests: Testing individual activities with mocks
- Integration tests: Testing workflow with mocked activities (recommended approach)
- End-to-end tests: Testing complete workflow execution

Based on Temporal testing documentation best practices.
"""

import pytest
import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from temporalio.testing import WorkflowEnvironment
from temporalio.client import Client
from temporalio.worker import Worker

from agentarea_execution.models import AgentExecutionRequest, AgentExecutionResult
from agentarea_execution.workflows.agent_execution import AgentExecutionWorkflow
from agentarea_execution.activities.agent_activities import (
    validate_agent_configuration_activity,
    discover_available_tools_activity,
    execute_agent_task_activity,
    persist_agent_memory_activity,
    publish_task_event_activity,
)
from agentarea_execution.interfaces import ActivityServicesInterface


class MockActivityServices:
    """Mock activity services for testing."""
    
    def __init__(self):
        self.agent_service = AsyncMock()
        self.mcp_service = AsyncMock()
        self.llm_service = AsyncMock()
        self.event_broker = AsyncMock()
        
        # Configure default return values
        self.agent_service.build_agent_config.return_value = {
            "name": "test_agent",
            "description": "Test agent",
            "instruction": "You are a helpful assistant",
            "model_instance": {
                "model_name": "gemini-2.0-flash",
                "provider": "google",
            },
            "tools_config": {
                "mcp_servers": [],
            },
        }
        
        self.agent_service.update_agent_memory.return_value = {
            "memory_entries_created": 2
        }
        
        self.mcp_service.get_server_instance.return_value = None
        self.mcp_service.get_server_tools.return_value = []
        
        self.event_broker.publish_event.return_value = None


@pytest.fixture
def mock_services():
    """Fixture providing mock services."""
    return MockActivityServices()


@pytest.fixture
def sample_request():
    """Fixture providing a sample execution request."""
    return AgentExecutionRequest(
        task_id=uuid4(),
        agent_id=uuid4(),
        user_id="test_user",
        task_query="What is the weather in New York?",
        max_reasoning_iterations=5,
        timeout_seconds=300,
    )


class TestAgentExecutionWorkflow:
    """Integration tests for AgentExecutionWorkflow (recommended approach)."""
    
    @pytest.mark.asyncio
    async def test_successful_agent_execution(self, sample_request, mock_services):
        """Test successful agent execution with mocked activities."""
        async with WorkflowEnvironment() as env:
            # Mock successful activity responses
            validation_result = {
                "valid": True,
                "errors": [],
                "agent_config": await mock_services.agent_service.build_agent_config(sample_request.agent_id),
            }
            
            tools_result = [
                {
                    "name": "test_tool",
                    "description": "A test tool",
                    "mcp_server_id": str(uuid4()),
                    "mcp_server_name": "test_server",
                }
            ]
            
            execution_result = {
                "success": True,
                "final_response": "The weather in New York is sunny and 25°C.",
                "conversation_history": [
                    {"role": "user", "content": sample_request.task_query},
                    {"role": "assistant", "content": "The weather in New York is sunny and 25°C."},
                ],
                "execution_metrics": {
                    "reasoning_iterations": 1,
                    "tool_calls": 1,
                    "execution_duration_seconds": 2.5,
                },
                "artifacts": [],
            }
            
            memory_result = {
                "success": True,
                "memory_entries_created": 2,
                "conversation_length": 2,
            }
            
            event_result = {
                "success": True,
                "event_type": "task_completed",
                "published_at": "2024-01-15T10:30:00Z",
            }
            
            # Configure activity mocks
            async def mock_validate_agent_configuration_activity(agent_id, activity_services):
                return validation_result
                
            async def mock_discover_available_tools_activity(agent_id, activity_services):
                return tools_result
                
            async def mock_execute_agent_task_activity(request, available_tools, activity_services):
                return execution_result
                
            async def mock_persist_agent_memory_activity(agent_id, task_id, conversation_history, task_result, activity_services):
                return memory_result
                
            async def mock_publish_task_event_activity(event_type, event_data, activity_services):
                return event_result
            
            # Create worker with mocked activities
            worker = Worker(
                env.client,
                task_queue="test-task-queue",
                workflows=[AgentExecutionWorkflow],
                activities=[
                    mock_validate_agent_configuration_activity,
                    mock_discover_available_tools_activity,
                    mock_execute_agent_task_activity,
                    mock_persist_agent_memory_activity,
                    mock_publish_task_event_activity,
                ],
            )
            
            # Start worker
            async with worker:
                # Execute workflow
                result = await env.client.execute_workflow(
                    AgentExecutionWorkflow.run,
                    sample_request,
                    id=f"test-workflow-{sample_request.task_id}",
                    task_queue="test-task-queue",
                    execution_timeout=timedelta(minutes=5),
                )
                
                # Verify result
                assert result.success is True
                assert "sunny" in result.final_response
                assert len(result.conversation_history) == 2
                assert result.execution_metrics["reasoning_iterations"] == 1
                assert result.execution_metrics["tool_calls"] == 1
                assert result.agent_id == sample_request.agent_id
                assert result.task_id == sample_request.task_id
    
    @pytest.mark.asyncio
    async def test_agent_validation_failure(self, sample_request, mock_services):
        """Test workflow behavior when agent validation fails."""
        async with WorkflowEnvironment() as env:
            # Mock validation failure
            validation_result = {
                "valid": False,
                "errors": ["Agent configuration is invalid"],
                "agent_config": None,
            }
            
            async def mock_validate_agent_configuration_activity(agent_id, activity_services):
                return validation_result
            
            # Create worker with mocked activities
            worker = Worker(
                env.client,
                task_queue="test-task-queue",
                workflows=[AgentExecutionWorkflow],
                activities=[mock_validate_agent_configuration_activity],
            )
            
            # Start worker
            async with worker:
                # Execute workflow - should fail
                with pytest.raises(Exception) as exc_info:
                    await env.client.execute_workflow(
                        AgentExecutionWorkflow.run,
                        sample_request,
                        id=f"test-workflow-{sample_request.task_id}",
                        task_queue="test-task-queue",
                        execution_timeout=timedelta(minutes=5),
                    )
                
                # Verify error contains validation failure
                assert "Agent configuration is invalid" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_agent_execution_failure_with_retry(self, sample_request, mock_services):
        """Test workflow behavior when agent execution fails but retries succeed."""
        async with WorkflowEnvironment() as env:
            # Mock successful validation and tool discovery
            validation_result = {
                "valid": True,
                "errors": [],
                "agent_config": await mock_services.agent_service.build_agent_config(sample_request.agent_id),
            }
            
            tools_result = []
            
            # Mock execution failure then success
            execution_attempts = 0
            async def mock_execute_agent_task_activity(request, available_tools, activity_services):
                nonlocal execution_attempts
                execution_attempts += 1
                
                if execution_attempts == 1:
                    # First attempt fails
                    return {
                        "success": False,
                        "error_message": "Temporary ADK execution failure",
                        "conversation_history": [
                            {"role": "user", "content": request.task_query},
                            {"role": "system", "content": "Error: Temporary ADK execution failure"},
                        ],
                        "execution_metrics": {
                            "reasoning_iterations": 0,
                            "tool_calls": 0,
                            "execution_duration_seconds": 0,
                        },
                        "artifacts": [],
                    }
                else:
                    # Second attempt succeeds
                    return {
                        "success": True,
                        "final_response": "The weather in New York is cloudy and 20°C.",
                        "conversation_history": [
                            {"role": "user", "content": request.task_query},
                            {"role": "assistant", "content": "The weather in New York is cloudy and 20°C."},
                        ],
                        "execution_metrics": {
                            "reasoning_iterations": 1,
                            "tool_calls": 1,
                            "execution_duration_seconds": 3.0,
                        },
                        "artifacts": [],
                    }
            
            async def mock_validate_agent_configuration_activity(agent_id, activity_services):
                return validation_result
                
            async def mock_discover_available_tools_activity(agent_id, activity_services):
                return tools_result
            
            # Create worker with mocked activities
            worker = Worker(
                env.client,
                task_queue="test-task-queue",
                workflows=[AgentExecutionWorkflow],
                activities=[
                    mock_validate_agent_configuration_activity,
                    mock_discover_available_tools_activity,
                    mock_execute_agent_task_activity,
                ],
            )
            
            # Start worker
            async with worker:
                # Execute workflow - should succeed after retry
                result = await env.client.execute_workflow(
                    AgentExecutionWorkflow.run,
                    sample_request,
                    id=f"test-workflow-{sample_request.task_id}",
                    task_queue="test-task-queue",
                    execution_timeout=timedelta(minutes=5),
                )
                
                # Verify result shows success after retry
                assert result.success is True
                assert "cloudy" in result.final_response
                assert execution_attempts == 2  # Verify retry occurred


class TestAgentExecutionActivities:
    """Unit tests for individual activities."""
    
    @pytest.mark.asyncio
    async def test_validate_agent_configuration_activity_success(self, mock_services):
        """Test successful agent configuration validation."""
        agent_id = uuid4()
        
        # Mock successful MCP server
        mock_services.mcp_service.get_server_instance.return_value = MagicMock(
            id=uuid4(),
            name="test_server",
            status="running"
        )
        
        result = await validate_agent_configuration_activity(agent_id, mock_services)
        
        assert result["valid"] is True
        assert len(result["errors"]) == 0
        assert result["agent_config"] is not None
        mock_services.agent_service.build_agent_config.assert_called_once_with(agent_id)
    
    @pytest.mark.asyncio
    async def test_validate_agent_configuration_activity_agent_not_found(self, mock_services):
        """Test validation when agent is not found."""
        agent_id = uuid4()
        
        # Mock agent not found
        mock_services.agent_service.build_agent_config.return_value = None
        
        result = await validate_agent_configuration_activity(agent_id, mock_services)
        
        assert result["valid"] is False
        assert f"Agent {agent_id} not found" in result["errors"]
    
    @pytest.mark.asyncio
    async def test_discover_available_tools_activity_success(self, mock_services):
        """Test successful tool discovery."""
        agent_id = uuid4()
        server_id = uuid4()
        
        # Mock agent config with MCP server
        mock_services.agent_service.build_agent_config.return_value = {
            "tools_config": {
                "mcp_servers": [
                    {
                        "id": str(server_id),
                        "name": "test_server",
                    }
                ]
            }
        }
        
        # Mock server instance and tools
        mock_services.mcp_service.get_server_instance.return_value = MagicMock(
            id=server_id,
            name="test_server",
            status="running"
        )
        
        mock_services.mcp_service.get_server_tools.return_value = [
            {
                "name": "search_tool",
                "description": "Search the web",
                "parameters": {"query": "string"},
            }
        ]
        
        result = await discover_available_tools_activity(agent_id, mock_services)
        
        assert len(result) == 1
        assert result[0]["name"] == "search_tool"
        assert result[0]["mcp_server_id"] == str(server_id)
        assert result[0]["mcp_server_name"] == "test_server"
    
    @pytest.mark.asyncio
    async def test_discover_available_tools_activity_no_servers(self, mock_services):
        """Test tool discovery when no MCP servers are configured."""
        agent_id = uuid4()
        
        # Mock agent config without MCP servers
        mock_services.agent_service.build_agent_config.return_value = {
            "tools_config": {
                "mcp_servers": []
            }
        }
        
        result = await discover_available_tools_activity(agent_id, mock_services)
        
        assert len(result) == 0


class TestEndToEndAgentExecution:
    """End-to-end tests with real Temporal server (optional - requires running Temporal server)."""
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_temporal_server_execution(self, sample_request):
        """Test execution against real Temporal server (requires running server)."""
        try:
            # Connect to real Temporal server
            client = await Client.connect("localhost:7233")
            
            # Create mock services
            mock_services = MockActivityServices()
            
            # Mock successful execution
            async def mock_execute_agent_task_activity(request, available_tools, activity_services):
                return {
                    "success": True,
                    "final_response": "Integration test response",
                    "conversation_history": [
                        {"role": "user", "content": request.task_query},
                        {"role": "assistant", "content": "Integration test response"},
                    ],
                    "execution_metrics": {
                        "reasoning_iterations": 1,
                        "tool_calls": 0,
                        "execution_duration_seconds": 1.0,
                    },
                    "artifacts": [],
                }
            
            # Create worker
            worker = Worker(
                client,
                task_queue="agent-execution-integration-test",
                workflows=[AgentExecutionWorkflow],
                activities=[mock_execute_agent_task_activity],
            )
            
            # Start worker and execute workflow
            async with worker:
                result = await client.execute_workflow(
                    AgentExecutionWorkflow.run,
                    sample_request,
                    id=f"integration-test-{sample_request.task_id}",
                    task_queue="agent-execution-integration-test",
                    execution_timeout=timedelta(minutes=5),
                )
                
                # Verify result
                assert result.success is True
                assert "Integration test response" in result.final_response
                
        except Exception as e:
            pytest.skip(f"Real Temporal server not available: {e}")


# Time-skipping tests (following Temporal best practices)
class TestTimeSkipping:
    """Tests demonstrating time-skipping capabilities."""
    
    @pytest.mark.asyncio
    async def test_workflow_timeout_handling(self, sample_request):
        """Test workflow timeout handling with time skipping."""
        async with WorkflowEnvironment() as env:
            # Mock slow activity that would normally timeout
            async def slow_execute_agent_task_activity(request, available_tools, activity_services):
                # This would normally take 10 minutes, but time-skipping makes it instant
                await asyncio.sleep(600)  # 10 minutes
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
            
            # Create worker with slow activity
            worker = Worker(
                env.client,
                task_queue="test-task-queue",
                workflows=[AgentExecutionWorkflow],
                activities=[slow_execute_agent_task_activity],
            )
            
            # Start worker
            async with worker:
                # Execute workflow with short timeout (should fail)
                with pytest.raises(Exception):
                    await env.client.execute_workflow(
                        AgentExecutionWorkflow.run,
                        sample_request,
                        id=f"timeout-test-{sample_request.task_id}",
                        task_queue="test-task-queue",
                        execution_timeout=timedelta(minutes=1),  # Shorter than activity duration
                    )


if __name__ == "__main__":
    # Run specific test
    pytest.main([__file__, "-v", "-s"]) 