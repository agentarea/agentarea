import concurrent.futures
import uuid
from datetime import timedelta
from typing import Any

import pytest
from agentarea_execution.models import AgentExecutionRequest
from agentarea_execution.workflows.agent_execution_workflow import (
    AgentExecutionWorkflow,
)
from temporalio import activity
from temporalio.client import WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker


class TestAgentExecutionWorkflowIntegration:
    @pytest.mark.asyncio
    async def test_workflow_with_tool_calls(self):
        """Test that the workflow properly handles tool calls by creating new activities."""
        env = await WorkflowEnvironment.start_time_skipping()
        async with env:
            task_queue_name = str(uuid.uuid4())
            workflow_id = str(uuid.uuid4())

            @activity.defn(name="build_agent_config_activity")
            async def mock_build_agent_config_activity(
                agent_id: uuid.UUID,
                execution_context: dict[str, Any] | None = None,
                step_type: str | None = None,
                override_model: str | None = None,
            ) -> dict[str, Any]:
                return {
                    "model": "gpt-4",
                    "name": "Test Agent",
                    "instruction": "You are a helpful assistant.",
                    "tools": []
                }

            @activity.defn(name="discover_available_tools_activity")
            async def mock_discover_available_tools_activity(
                agent_id: uuid.UUID,
            ) -> list[dict[str, Any]]:
                return [
                    {
                        "name": "calculator",
                        "description": "Calculate mathematical expressions",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "expression": {"type": "string", "description": "Math expression to calculate"}
                            },
                            "required": ["expression"]
                        }
                    }
                ]

            # Track LLM call count to simulate iterative behavior
            llm_call_count = 0
            
            @activity.defn(name="call_llm_activity")
            async def mock_call_llm_activity(
                messages: list[dict[str, Any]],
                model: str,
                tools: list[dict[str, Any]] | None = None,
            ) -> dict[str, Any]:
                nonlocal llm_call_count
                llm_call_count += 1
                
                # First call - LLM decides to use calculator
                if llm_call_count == 1:
                    return {
                        "content": "I need to calculate 2 + 2. Let me use the calculator.",
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "name": "calculator",
                                "args": {"expression": "2 + 2"}
                            }
                        ],
                        "finish_reason": "tool_call"
                    }
                
                # Second call - LLM provides final answer after tool execution
                elif llm_call_count == 2:
                    return {
                        "content": "Based on my calculation, 2 + 2 equals 4.",
                        "tool_calls": [],
                        "finish_reason": "stop"
                    }
                
                # Fallback
                return {
                    "content": "I have completed the task.",
                    "tool_calls": [],
                    "finish_reason": "stop"
                }

            @activity.defn(name="execute_mcp_tool_activity")
            async def mock_execute_mcp_tool_activity(
                tool_name: str,
                tool_args: dict[str, Any],
                server_instance_id: uuid.UUID | None = None,
            ) -> dict[str, Any]:
                if tool_name == "calculator" and tool_args.get("expression") == "2 + 2":
                    return {
                        "success": True,
                        "result": "4",
                        "tool_name": tool_name,
                    }
                return {
                    "success": True,
                    "result": f"Mock result for {tool_name}",
                    "tool_name": tool_name,
                }

            @activity.defn(name="check_task_completion_activity")
            async def mock_check_task_completion_activity(
                messages: list[dict[str, Any]],
                current_iteration: int,
                max_iterations: int,
            ) -> dict[str, Any]:
                # Complete after 2 LLM calls for tool test, or if finish_reason is 'stop'
                if llm_call_count >= 2:
                    return {"should_complete": True, "reason": "test_complete"}
                # Check last assistant message for finish_reason
                for msg in reversed(messages):
                    if msg.get("role") == "assistant" and msg.get("finish_reason") == "stop":
                        return {"should_complete": True, "reason": "llm_stop"}
                return {"should_complete": False, "reason": "continue"}

            with concurrent.futures.ThreadPoolExecutor(max_workers=100) as activity_executor:
                worker = Worker(
                    env.client,
                    task_queue=task_queue_name,
                    workflows=[AgentExecutionWorkflow],
                    activities=[
                        mock_build_agent_config_activity,
                        mock_discover_available_tools_activity,
                        mock_call_llm_activity,
                        mock_execute_mcp_tool_activity,
                        mock_check_task_completion_activity,
                    ],
                    activity_executor=activity_executor,
                )

                async with worker:
                    sample_request = AgentExecutionRequest(
                        task_id=uuid.uuid4(),
                        agent_id=uuid.uuid4(),
                        user_id="integration_test_user",
                        task_query="What is 2 + 2?",
                        timeout_seconds=30,
                        max_reasoning_iterations=5,
                    )

                    handle = await env.client.start_workflow(
                        AgentExecutionWorkflow.run,
                        sample_request,
                        id=workflow_id,
                        task_queue=task_queue_name,
                        execution_timeout=timedelta(minutes=2),
                    )

                    assert WorkflowExecutionStatus.RUNNING == (await handle.describe()).status

                    # Check execution status during workflow
                    status = await handle.query("get_execution_status")
                    assert "status" in status
                    assert "workflow_type" in status

                    result = await handle.result()

                    # Verify the workflow completed successfully
                    assert result.success is True
                    assert result.agent_id == sample_request.agent_id
                    assert result.task_id == sample_request.task_id
                    assert result.final_response is not None
                    assert "4" in result.final_response  # Should contain the calculation result
                    
                    # Verify tool calls were made
                    assert result.total_tool_calls == 1
                    assert result.reasoning_iterations_used >= 1
                    
                    # Verify conversation history structure
                    assert len(result.conversation_history) >= 4  # user -> assistant -> tool -> assistant
                    
                    # Check that we have the right message types
                    message_roles = [msg["role"] for msg in result.conversation_history]
                    assert "user" in message_roles
                    assert "assistant" in message_roles
                    assert "tool" in message_roles
                    
                    # Verify tool execution happened
                    tool_messages = [msg for msg in result.conversation_history if msg["role"] == "tool"]
                    assert len(tool_messages) == 1
                    assert "4" in str(tool_messages[0]["content"])
                    
                    print(f"✅ Test passed! Tool calls made: {result.total_tool_calls}")
                    print(f"✅ Conversation history: {len(result.conversation_history)} messages")
                    print(f"✅ Final response: {result.final_response}")

    @pytest.mark.asyncio
    async def test_workflow_without_tool_calls(self):
        """Test workflow when no tools are needed."""
        env = await WorkflowEnvironment.start_time_skipping()
        async with env:
            task_queue_name = str(uuid.uuid4())
            workflow_id = str(uuid.uuid4())

            @activity.defn(name="build_agent_config_activity")
            async def mock_build_agent_config_activity(
                agent_id: uuid.UUID,
                execution_context: dict[str, Any] | None = None,
                step_type: str | None = None,
                override_model: str | None = None,
            ) -> dict[str, Any]:
                return {
                    "model": "gpt-4",
                    "name": "Test Agent",
                    "instruction": "You are a helpful assistant.",
                    "tools": []
                }

            @activity.defn(name="discover_available_tools_activity")
            async def mock_discover_available_tools_activity(
                agent_id: uuid.UUID,
            ) -> list[dict[str, Any]]:
                return []

            @activity.defn(name="call_llm_activity")
            async def mock_call_llm_activity(
                messages: list[dict[str, Any]],
                model: str,
                tools: list[dict[str, Any]] | None = None,
            ) -> dict[str, Any]:
                return {
                    "content": "Hello! I'm here to help you with your questions.",
                    "tool_calls": [],
                    "finish_reason": "stop"
                }

            @activity.defn(name="execute_mcp_tool_activity")
            async def mock_execute_mcp_tool_activity(
                tool_name: str,
                tool_args: dict[str, Any],
                server_instance_id: uuid.UUID | None = None,
            ) -> dict[str, Any]:
                return {"success": True, "result": "Mock result", "tool_name": tool_name}

            @activity.defn(name="check_task_completion_activity")
            async def mock_check_task_completion_activity(
                messages: list[dict[str, Any]],
                current_iteration: int,
                max_iterations: int,
            ) -> dict[str, Any]:
                # Complete after first iteration for this test
                if current_iteration == 1:
                    return {"should_complete": True, "reason": "test_complete"}
                return {"should_complete": False, "reason": "continue"}

            with concurrent.futures.ThreadPoolExecutor(max_workers=100) as activity_executor:
                worker = Worker(
                    env.client,
                    task_queue=task_queue_name,
                    workflows=[AgentExecutionWorkflow],
                    activities=[
                        mock_build_agent_config_activity,
                        mock_discover_available_tools_activity,
                        mock_call_llm_activity,
                        mock_execute_mcp_tool_activity,
                        mock_check_task_completion_activity,
                    ],
                    activity_executor=activity_executor,
                )

                async with worker:
                    sample_request = AgentExecutionRequest(
                        task_id=uuid.uuid4(),
                        agent_id=uuid.uuid4(),
                        user_id="integration_test_user",
                        task_query="Hello, how are you?",
                        timeout_seconds=30,
                        max_reasoning_iterations=3,
                    )

                    handle = await env.client.start_workflow(
                        AgentExecutionWorkflow.run,
                        sample_request,
                        id=workflow_id,
                        task_queue=task_queue_name,
                        execution_timeout=timedelta(minutes=2),
                    )

                    result = await handle.result()

                    # Verify the workflow completed successfully without tools
                    assert result.success is True
                    assert result.agent_id == sample_request.agent_id
                    assert result.task_id == sample_request.task_id
                    assert result.final_response is not None
                    assert result.total_tool_calls == 0  # No tools should be called
                    assert result.reasoning_iterations_used == 1  # Should complete in one iteration
                    
                    # Verify conversation history has user and assistant messages
                    assert len(result.conversation_history) >= 2
                    message_roles = [msg["role"] for msg in result.conversation_history]
                    assert "user" in message_roles
                    assert "assistant" in message_roles
                    assert "tool" not in message_roles  # No tool messages
                    
                    print(f"✅ Test passed! No tool calls made: {result.total_tool_calls}")
                    print(f"✅ Completed in {result.reasoning_iterations_used} iteration(s)")
                    print(f"✅ Final response: {result.final_response}")
