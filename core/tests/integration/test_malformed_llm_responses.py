"""Test handling of malformed LLM responses that cause workflows to never finish."""

import json
import logging
from datetime import timedelta
from uuid import uuid4

import pytest
from agentarea_execution.models import AgentExecutionRequest
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_workflow_with_malformed_tool_calls_in_content():
    """Test workflow with malformed LLM responses where tool_calls is null but content has JSON."""

    execution_request = AgentExecutionRequest(
        agent_id=uuid4(),
        task_id=uuid4(),
        user_id="test-user",
        task_query="Complete a simple test task",
        task_parameters={"success_criteria": ["Task completed successfully"], "max_iterations": 5},
        budget_usd=1.0,
        requires_human_approval=False,
    )

    activity_calls = []
    llm_call_count = 0

    @activity.defn(name="build_agent_config_activity")
    async def mock_build_agent_config(*args, **kwargs):
        activity_calls.append("build_agent_config")
        return {
            "id": str(execution_request.agent_id),
            "name": "Test Agent",
            "instruction": "Complete tasks efficiently",
            "model_id": str(uuid4()),
            "tools_config": {},
            "events_config": {},
            "planning": False,
        }

    @activity.defn(name="discover_available_tools_activity")
    async def mock_discover_tools(*args, **kwargs):
        activity_calls.append("discover_tools")
        return [
            {
                "type": "function",
                "function": {
                    "name": "task_complete",
                    "description": "Mark task as completed",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            }
        ]

    @activity.defn(name="call_llm_activity")
    async def mock_call_llm(*args, **kwargs):
        nonlocal llm_call_count
        llm_call_count += 1
        activity_calls.append(f"call_llm_{llm_call_count}")

        if llm_call_count == 1:
            # First call: Malformed response like production (tool_calls is null, content has JSON)
            return {
                "content": '{\n  "name": "task_complete",\n  "arguments": {}\n}',
                "cost": 0,
                "role": "assistant",
                "tool_calls": None,  # This is the bug - should contain the tool call
                "usage": {"completion_tokens": 0, "prompt_tokens": 0, "total_tokens": 0},
            }
        else:
            # Second call: Another malformed response with arguments
            return {
                "content": '{"name": "task_complete", "arguments": {"result": "Task completed successfully after parsing from content field"}}',
                "cost": 0,
                "role": "assistant",
                "tool_calls": None,  # Still malformed
                "usage": {"completion_tokens": 0, "prompt_tokens": 0, "total_tokens": 0},
            }

    @activity.defn(name="execute_mcp_tool_activity")
    async def mock_execute_tool(tool_name: str, tool_args: dict, **kwargs):
        activity_calls.append(f"execute_tool_{tool_name}")
        logger.info(f"Mock execute tool called: {tool_name} with args: {tool_args}")
        if tool_name == "task_complete":
            result = {
                "success": True,
                "completed": True,
                "result": tool_args.get("result", "Task completed"),
                "tool_name": "task_complete",
            }
            logger.info(f"Mock task_complete returning: {result}")
            return result
        return {"success": False, "result": "Unknown tool"}

    @activity.defn(name="evaluate_goal_progress_activity")
    async def mock_evaluate_goal(*args, **kwargs):
        activity_calls.append("evaluate_goal")
        return {"goal_achieved": False, "final_response": None}

    @activity.defn(name="publish_workflow_events_activity")
    async def mock_publish_events(*args, **kwargs):
        activity_calls.append("publish_events")
        return True

    env = await WorkflowEnvironment.start_time_skipping()
    try:
        activities = [
            mock_build_agent_config,
            mock_discover_tools,
            mock_call_llm,
            mock_execute_tool,
            mock_evaluate_goal,
            mock_publish_events,
        ]

        async with Worker(
            env.client,
            task_queue="test-queue",
            workflows=[AgentExecutionWorkflow],
            activities=activities,
        ):
            logger.info("Starting workflow with malformed LLM responses")

            result = await env.client.execute_workflow(
                AgentExecutionWorkflow.run,
                execution_request,
                id=f"test-workflow-{uuid4()}",
                task_queue="test-queue",
                execution_timeout=timedelta(seconds=15),
            )

            logger.info(
                f"Workflow completed: success={result.success}, iterations={result.reasoning_iterations_used}"
            )
            logger.info(f"Activity calls: {activity_calls}")

            # Should complete successfully despite malformed responses
            assert result.success is True, f"Expected success=True, got {result.success}"
            assert "execute_tool_task_complete" in activity_calls, (
                "Should have executed task_complete tool"
            )
            assert result.reasoning_iterations_used >= 1, (
                "Should have completed at least 1 iteration"
            )

    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_workflow_with_various_malformed_formats():
    """Test workflow with various malformed response formats."""

    execution_request = AgentExecutionRequest(
        agent_id=uuid4(),
        task_id=uuid4(),
        user_id="test-user",
        task_query="Test malformed responses",
        task_parameters={"success_criteria": ["Task completed"], "max_iterations": 10},
        budget_usd=1.0,
        requires_human_approval=False,
    )

    activity_calls = []
    llm_call_count = 0

    # Various malformed response formats to test
    malformed_responses = [
        # Format 1: JSON in content, tool_calls null
        {
            "content": '{"name": "task_complete", "arguments": {"result": "Format 1 test"}}',
            "tool_calls": None,
            "role": "assistant",
            "cost": 0,
            "usage": {"total_tokens": 0},
        },
        # Format 2: Partial JSON in content
        {
            "content": 'I will complete the task: {"name": "task_complete", "arguments": {"result": "Format 2 test"}}',
            "tool_calls": None,
            "role": "assistant",
            "cost": 0,
            "usage": {"total_tokens": 0},
        },
        # Format 3: Just mention task_complete
        {
            "content": "I need to call task_complete to finish this",
            "tool_calls": None,
            "role": "assistant",
            "cost": 0,
            "usage": {"total_tokens": 0},
        },
        # Format 4: Malformed JSON
        {
            "content": '{"name": "task_complete", "arguments": {result: "Format 4 test"}}',  # Missing quotes
            "tool_calls": None,
            "role": "assistant",
            "cost": 0,
            "usage": {"total_tokens": 0},
        },
        # Format 5: Finally a proper completion
        {
            "content": '{"name": "task_complete", "arguments": {"result": "Successfully completed after handling malformed responses"}}',
            "tool_calls": None,
            "role": "assistant",
            "cost": 0,
            "usage": {"total_tokens": 0},
        },
    ]

    @activity.defn(name="build_agent_config_activity")
    async def mock_build_agent_config(*args, **kwargs):
        return {
            "id": str(execution_request.agent_id),
            "name": "Test Agent",
            "instruction": "Complete tasks",
            "model_id": str(uuid4()),
            "tools_config": {},
            "events_config": {},
            "planning": False,
        }

    @activity.defn(name="discover_available_tools_activity")
    async def mock_discover_tools(*args, **kwargs):
        return [
            {
                "type": "function",
                "function": {
                    "name": "task_complete",
                    "description": "Mark task as completed",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            }
        ]

    @activity.defn(name="call_llm_activity")
    async def mock_call_llm(*args, **kwargs):
        nonlocal llm_call_count
        llm_call_count += 1

        if llm_call_count <= len(malformed_responses):
            response = malformed_responses[llm_call_count - 1]
            logger.info(f"LLM call {llm_call_count}: {response['content'][:50]}...")
            return response
        else:
            # Fallback response
            return {
                "content": "Still working...",
                "tool_calls": None,
                "role": "assistant",
                "cost": 0,
                "usage": {"total_tokens": 0},
            }

    @activity.defn(name="execute_mcp_tool_activity")
    async def mock_execute_tool(tool_name: str, tool_args: dict, **kwargs):
        activity_calls.append(f"execute_tool_{tool_name}")
        if tool_name == "task_complete":
            return {
                "success": True,
                "completed": True,
                "result": tool_args.get("result", "Task completed"),
                "tool_name": "task_complete",
            }
        return {"success": False, "result": "Unknown tool"}

    @activity.defn(name="evaluate_goal_progress_activity")
    async def mock_evaluate_goal(*args, **kwargs):
        return {"goal_achieved": False, "final_response": None}

    @activity.defn(name="publish_workflow_events_activity")
    async def mock_publish_events(*args, **kwargs):
        return True

    env = await WorkflowEnvironment.start_time_skipping()
    try:
        activities = [
            mock_build_agent_config,
            mock_discover_tools,
            mock_call_llm,
            mock_execute_tool,
            mock_evaluate_goal,
            mock_publish_events,
        ]

        async with Worker(
            env.client,
            task_queue="test-queue",
            workflows=[AgentExecutionWorkflow],
            activities=activities,
        ):
            result = await env.client.execute_workflow(
                AgentExecutionWorkflow.run,
                execution_request,
                id=f"test-workflow-{uuid4()}",
                task_queue="test-queue",
                execution_timeout=timedelta(seconds=20),
            )

            logger.info(
                f"Final result: success={result.success}, iterations={result.reasoning_iterations_used}"
            )
            logger.info(f"Activity calls: {activity_calls}")

            # Should eventually complete by parsing malformed responses
            assert "execute_tool_task_complete" in activity_calls, (
                "Should have executed task_complete despite malformed responses"
            )

    finally:
        await env.shutdown()


def test_tool_call_extractor_with_production_data():
    """Test the ToolCallExtractor with actual production data."""
    from agentarea_execution.workflows.helpers import ToolCallExtractor

    # Test case 1: Production data - first call
    message1 = {
        "content": '{\n  "name": "task_complete",\n  "arguments": {}\n}',
        "cost": 0,
        "role": "assistant",
        "tool_calls": None,
        "usage": {"completion_tokens": 0, "prompt_tokens": 0, "total_tokens": 0},
    }

    tool_calls1 = ToolCallExtractor.extract_tool_calls(message1)
    assert len(tool_calls1) == 1, f"Expected 1 tool call, got {len(tool_calls1)}"
    assert tool_calls1[0].function["name"] == "task_complete", (
        f"Expected task_complete, got {tool_calls1[0].function['name']}"
    )

    # Test case 2: Production data - second call
    message2 = {
        "content": '{"name": "task_complete", "arguments": {"result": "Since no specific task was provided and the goal \'test\' is vague, I\'ve completed this iteration with a basic task completion message as instructed."}}',
        "cost": 0,
        "role": "assistant",
        "tool_calls": None,
        "usage": {"completion_tokens": 0, "prompt_tokens": 0, "total_tokens": 0},
    }

    tool_calls2 = ToolCallExtractor.extract_tool_calls(message2)
    assert len(tool_calls2) == 1, f"Expected 1 tool call, got {len(tool_calls2)}"
    assert tool_calls2[0].function["name"] == "task_complete", (
        f"Expected task_complete, got {tool_calls2[0].function['name']}"
    )

    # Verify arguments are properly extracted
    args = json.loads(tool_calls2[0].function["arguments"])
    assert "result" in args, "Expected 'result' in arguments"
    assert "task was provided" in args["result"], "Expected result message to be preserved"

    print("✅ Tool call extractor correctly handles production malformed data")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v", "-s"])
