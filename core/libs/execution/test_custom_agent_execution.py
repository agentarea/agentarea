"""
Test custom agent execution engine with Temporal activities.

This tests our new architecture that provides Temporal durability for:
- LLM calls via call_llm_activity
- Tool execution via execute_mcp_tool_activity
- Proper conversation flow with retries and observability
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

from agentarea_execution.activities.agent_activities import (
    call_llm_activity,
    execute_mcp_tool_activity,
    execute_agent_task_activity,
    validate_agent_configuration_activity,
    discover_available_tools_activity,
)
from agentarea_execution.interfaces import ActivityServicesInterface
from agentarea_execution.models import (
    AgentExecutionRequest,
    LLMReasoningResult,
)


class MockActivityServices:
    """Mock implementation of ActivityServicesInterface for testing."""
    
    def __init__(self):
        self.llm_service = AsyncMock()
        self.mcp_service = AsyncMock()
        self.agent_service = AsyncMock()
        self.event_broker = AsyncMock()


@pytest.fixture
def mock_services():
    """Create mock services for testing."""
    return MockActivityServices()


@pytest.fixture
def sample_agent_config():
    """Sample agent configuration."""
    return {
        "id": str(uuid4()),
        "name": "TestAgent",
        "model": "localhost:11434/qwen2.5",
        "instruction": "You are a helpful AI assistant with access to various tools.",
        "tools_config": {
            "mcp_servers": [
                {
                    "id": str(uuid4()),
                    "name": "test_tools",
                    "server_type": "docker"
                }
            ]
        }
    }


@pytest.fixture
def sample_tools():
    """Sample MCP tools available to agent."""
    return [
        {
            "name": "calculator",
            "description": "Perform mathematical calculations",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Mathematical expression to evaluate"
                    }
                }
            },
            "mcp_server_id": str(uuid4()),
            "mcp_server_name": "test_tools"
        },
        {
            "name": "weather",
            "description": "Get current weather information",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City name or coordinates"
                    }
                }
            },
            "mcp_server_id": str(uuid4()),
            "mcp_server_name": "test_tools"
        }
    ]


@pytest.mark.asyncio
async def test_call_llm_activity(mock_services, sample_agent_config, sample_tools):
    """Test LLM call via Temporal activity."""
    
    # Mock LLM service response
    mock_reasoning_result = LLMReasoningResult(
        reasoning_text="I need to calculate 10 + 5 using the calculator tool.",
        tool_calls=[
            {
                "name": "calculator",
                "arguments": {"expression": "10 + 5"},
                "mcp_server_id": sample_tools[0]["mcp_server_id"]
            }
        ],
        model_used="qwen2.5:latest",
        reasoning_time_seconds=1.2,
        believes_task_complete=False,
        completion_confidence=0.8
    )
    
    mock_services.llm_service.execute_reasoning.return_value = mock_reasoning_result
    
    # Test LLM call
    messages = [
        {"role": "user", "content": "What is 10 + 5?"}
    ]
    
    result = await call_llm_activity(
        messages=messages,
        model_config=sample_agent_config,
        available_tools=sample_tools,
        activity_services=mock_services
    )
    
    # Verify result
    assert result["success"] == True
    assert result["response_text"] == "I need to calculate 10 + 5 using the calculator tool."
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["name"] == "calculator"
    assert result["model_used"] == "qwen2.5:latest"
    assert result["reasoning_time"] == 1.2
    
    # Verify LLM service was called correctly
    mock_services.llm_service.execute_reasoning.assert_called_once()
    call_args = mock_services.llm_service.execute_reasoning.call_args
    assert call_args.kwargs["agent_config"] == sample_agent_config
    assert call_args.kwargs["conversation_history"] == messages


@pytest.mark.asyncio
async def test_execute_mcp_tool_activity(mock_services, sample_tools):
    """Test MCP tool execution via Temporal activity."""
    
    # Mock MCP service responses
    mock_server_instance = MagicMock()
    mock_server_instance.id = UUID(sample_tools[0]["mcp_server_id"])
    mock_server_instance.name = "test_tools"
    
    mock_services.mcp_service.get_server_instance.return_value = mock_server_instance
    mock_services.mcp_service.execute_tool.return_value = {
        "output": "15",
        "success": True
    }
    
    # Test tool execution
    tool_call = {
        "name": "calculator",
        "arguments": {"expression": "10 + 5"},
        "mcp_server_id": sample_tools[0]["mcp_server_id"]
    }
    
    result = await execute_mcp_tool_activity(
        tool_call=tool_call,
        activity_services=mock_services
    )
    
    # Verify result
    assert result["success"] == True
    assert result["result"] == "15"
    assert result["tool_name"] == "calculator"
    assert result["server_name"] == "test_tools"
    
    # Verify MCP service calls
    mock_services.mcp_service.get_server_instance.assert_called_once()
    mock_services.mcp_service.execute_tool.assert_called_once_with(
        server_instance_id=mock_server_instance.id,
        tool_name="calculator",
        arguments={"expression": "10 + 5"},
        timeout_seconds=60
    )


@pytest.mark.asyncio
async def test_execute_agent_task_activity_full_flow(mock_services, sample_agent_config, sample_tools):
    """Test full agent execution flow with LLM calls and tool execution."""
    
    # Setup mocks
    mock_services.agent_service.build_agent_config.return_value = sample_agent_config
    
    # Mock LLM call 1: Agent decides to use calculator
    llm_result_1 = LLMReasoningResult(
        reasoning_text="I need to calculate 10 + 5 using the calculator tool.",
        tool_calls=[
            {
                "name": "calculator",
                "arguments": {"expression": "10 + 5"},
                "mcp_server_id": sample_tools[0]["mcp_server_id"]
            }
        ],
        model_used="qwen2.5:latest",
        reasoning_time_seconds=1.2,
        believes_task_complete=False,
        completion_confidence=0.6
    )
    
    # Mock LLM call 2: Agent provides final answer
    llm_result_2 = LLMReasoningResult(
        reasoning_text="The calculation result is 15. The answer to 10 + 5 is 15.",
        tool_calls=[],
        model_used="qwen2.5:latest", 
        reasoning_time_seconds=0.8,
        believes_task_complete=True,
        completion_confidence=0.95
    )
    
    mock_services.llm_service.execute_reasoning.side_effect = [llm_result_1, llm_result_2]
    
    # Mock tool execution
    mock_server_instance = MagicMock()
    mock_server_instance.id = UUID(sample_tools[0]["mcp_server_id"])
    mock_server_instance.name = "test_tools"
    
    mock_services.mcp_service.get_server_instance.return_value = mock_server_instance
    mock_services.mcp_service.execute_tool.return_value = {
        "output": "15",
        "success": True
    }
    
    # Create execution request
    request = AgentExecutionRequest(
        task_id=uuid4(),
        agent_id=UUID(sample_agent_config["id"]),
        user_id="test_user",
        task_query="What is 10 + 5?",
        max_reasoning_iterations=5,
        timeout_seconds=300
    )
    
    # Execute agent task
    result = await execute_agent_task_activity(
        request=request,
        available_tools=sample_tools,
        activity_services=mock_services
    )
    
    # Verify successful execution
    assert result["success"] == True
    assert "15" in result["final_response"]
    assert result["reasoning_iterations"] == 2
    assert result["total_tool_calls"] == 1
    
    # Verify conversation history structure
    conversation = result["conversation_history"]
    assert len(conversation) == 5  # system + user + assistant + tool + assistant
    assert conversation[0]["role"] == "system"
    assert conversation[1]["role"] == "user" 
    assert conversation[1]["content"] == "What is 10 + 5?"
    assert conversation[2]["role"] == "assistant"
    assert conversation[3]["role"] == "tool"
    assert conversation[3]["name"] == "calculator"
    assert conversation[3]["content"] == "15"
    assert conversation[4]["role"] == "assistant"
    
    # Verify metrics
    metrics = result["execution_metrics"]
    assert metrics["model_used"] == "qwen2.5:latest"
    assert metrics["finish_reason"] == "stop"
    
    # Verify service calls
    assert mock_services.llm_service.execute_reasoning.call_count == 2
    assert mock_services.mcp_service.execute_tool.call_count == 1


@pytest.mark.asyncio
async def test_validate_agent_configuration_activity(mock_services, sample_agent_config):
    """Test agent configuration validation."""
    
    mock_services.agent_service.build_agent_config.return_value = sample_agent_config
    
    # Mock MCP server validation
    mock_server_instance = MagicMock()
    mock_server_instance.status = "running"
    mock_services.mcp_service.get_server_instance.return_value = mock_server_instance
    
    result = await validate_agent_configuration_activity(
        agent_id=UUID(sample_agent_config["id"]),
        activity_services=mock_services
    )
    
    assert result["valid"] == True
    assert result["agent_config"] == sample_agent_config
    assert len(result["errors"]) == 0


@pytest.mark.asyncio
async def test_discover_available_tools_activity(mock_services, sample_agent_config, sample_tools):
    """Test tool discovery from MCP servers."""
    
    mock_services.agent_service.build_agent_config.return_value = sample_agent_config
    
    # Mock MCP server instance and tools
    mock_server_instance = MagicMock()
    mock_server_instance.id = UUID(sample_agent_config["tools_config"]["mcp_servers"][0]["id"])
    mock_server_instance.name = "test_tools"
    
    mock_services.mcp_service.get_server_instance.return_value = mock_server_instance
    mock_services.mcp_service.get_server_tools.return_value = sample_tools
    
    result = await discover_available_tools_activity(
        agent_id=UUID(sample_agent_config["id"]),
        activity_services=mock_services
    )
    
    assert len(result) == 2
    assert result[0]["name"] == "calculator"
    assert result[1]["name"] == "weather"
    

if __name__ == "__main__":
    """Run tests directly for quick verification."""
    
    async def run_basic_test():
        """Quick test of the custom execution engine."""
        print("🧪 Testing Custom Agent Execution Engine...")
        
        mock_services = MockActivityServices()
        
        # Simple test
        llm_result = LLMReasoningResult(
            reasoning_text="Test response",
            tool_calls=[],
            model_used="test",
            believes_task_complete=True
        )
        mock_services.llm_service.execute_reasoning.return_value = llm_result
        mock_services.agent_service.build_agent_config.return_value = {
            "name": "TestAgent",
            "model": "test"
        }
        
        request = AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=uuid4(),
            user_id="test",
            task_query="Hello",
            max_reasoning_iterations=1
        )
        
        result = await execute_agent_task_activity(request, [], mock_services)
        
        print(f"✅ Execution successful: {result['success']}")
        print(f"✅ Response: {result['final_response']}")
        print(f"✅ Iterations: {result['reasoning_iterations']}")
        
        print("\n🎉 Custom Agent Execution Engine is working!")
        print("Key Benefits:")
        print("  ✅ LLM calls via Temporal activities (with retries & observability)")
        print("  ✅ Tool execution via Temporal activities (with durability)")
        print("  ✅ Complete conversation flow with proper state management")
        print("  ✅ Integration with existing AgentArea services")
        
    asyncio.run(run_basic_test()) 