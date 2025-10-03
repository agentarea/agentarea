"""Test workflow edge cases that might cause infinite loops."""

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
async def test_workflow_with_llm_never_calling_task_complete():
    """Test workflow when LLM never calls task_complete - should hit max iterations."""

    execution_request = AgentExecutionRequest(
        agent_id=uuid4(),
        task_id=uuid4(),
        user_id="test-user",
        task_query="Complete a simple test task",
        task_parameters={
            "success_criteria": ["Task completed successfully"],
            "max_iterations": 3,  # Low limit to test termination
        },
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

        # LLM never calls task_complete, just keeps thinking
        return {
            "role": "assistant",
            "content": f"I'm still working on this task... (iteration {llm_call_count})",
            "tool_calls": None,  # No tool calls
            "cost": 0.001,
            "usage": {"total_tokens": 30},
        }

    @activity.defn(name="execute_mcp_tool_activity")
    async def mock_execute_tool(tool_name: str, tool_args: dict, **kwargs):
        activity_calls.append(f"execute_tool_{tool_name}")
        return {"success": False, "result": "Should not be called"}

    @activity.defn(name="evaluate_goal_progress_activity")
    async def mock_evaluate_goal(*args, **kwargs):
        activity_calls.append("evaluate_goal")
        # Goal is never achieved
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
            result = await env.client.execute_workflow(
                AgentExecutionWorkflow.run,
                execution_request,
                id=f"test-workflow-{uuid4()}",
                task_queue="test-queue",
                execution_timeout=timedelta(seconds=15),
            )

            # Should complete due to max iterations, not success
            assert result.success is False, "Should not be successful when max iterations reached"
            assert result.reasoning_iterations_used == 2, (
                f"Expected 2 completed iterations, got {result.reasoning_iterations_used}"
            )
            assert llm_call_count == 2, f"Expected 2 LLM calls, got {llm_call_count}"

            logger.info(f"Activity calls: {activity_calls}")
            logger.info(f"LLM call count: {llm_call_count}")
            logger.info(
                f"Final result: success={result.success}, iterations={result.reasoning_iterations_used}"
            )
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_workflow_with_llm_calling_task_complete_but_unsuccessful():
    """Test workflow when LLM calls task_complete but it returns unsuccessful."""

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
        activity_calls.append("call_llm")
        # LLM calls task_complete
        return {
            "role": "assistant",
            "content": "I think I'm done.",
            "tool_calls": [
                {
                    "id": "call_complete",
                    "type": "function",
                    "function": {
                        "name": "task_complete",
                        "arguments": json.dumps({"result": "Task attempted"}),
                    },
                }
            ],
            "cost": 0.001,
            "usage": {"total_tokens": 40},
        }

    @activity.defn(name="execute_mcp_tool_activity")
    async def mock_execute_tool(tool_name: str, tool_args: dict, **kwargs):
        activity_calls.append(f"execute_tool_{tool_name}")
        if tool_name == "task_complete":
            # Return unsuccessful completion
            return {
                "success": False,  # Not successful!
                "completed": False,  # Not completed!
                "result": "Task failed to complete properly",
                "tool_name": "task_complete",
            }
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
            result = await env.client.execute_workflow(
                AgentExecutionWorkflow.run,
                execution_request,
                id=f"test-workflow-{uuid4()}",
                task_queue="test-queue",
                execution_timeout=timedelta(seconds=15),
            )

            # Should continue after unsuccessful task_complete
            # This tests that the workflow doesn't get stuck when task_complete fails
            logger.info(
                f"Final result: success={result.success}, iterations={result.reasoning_iterations_used}"
            )
            logger.info(f"Activity calls: {activity_calls}")

            # The workflow should continue and eventually hit max iterations or succeed through goal evaluation
            assert result.reasoning_iterations_used >= 1, "Should have at least 1 iteration"
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_workflow_with_empty_llm_responses():
    """Test workflow when LLM returns empty responses."""

    execution_request = AgentExecutionRequest(
        agent_id=uuid4(),
        task_id=uuid4(),
        user_id="test-user",
        task_query="Complete a simple test task",
        task_parameters={"success_criteria": ["Task completed successfully"], "max_iterations": 3},
        budget_usd=1.0,
        requires_human_approval=False,
    )

    activity_calls = []

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
        activity_calls.append("call_llm")
        # LLM returns empty response
        return {
            "role": "assistant",
            "content": "",  # Empty content
            "tool_calls": None,  # No tool calls
            "cost": 0.001,
            "usage": {"total_tokens": 10},
        }

    @activity.defn(name="execute_mcp_tool_activity")
    async def mock_execute_tool(tool_name: str, tool_args: dict, **kwargs):
        activity_calls.append(f"execute_tool_{tool_name}")
        return {"success": False, "result": "Should not be called"}

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
            result = await env.client.execute_workflow(
                AgentExecutionWorkflow.run,
                execution_request,
                id=f"test-workflow-{uuid4()}",
                task_queue="test-queue",
                execution_timeout=timedelta(seconds=15),
            )

            # Should handle empty responses and eventually terminate
            logger.info(
                f"Final result: success={result.success}, iterations={result.reasoning_iterations_used}"
            )
            logger.info(f"Activity calls: {activity_calls}")

            assert result.reasoning_iterations_used == 2, (
                "Should hit max iterations with empty responses"
            )
            assert result.success is False, "Should not be successful with empty responses"
    finally:
        await env.shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v", "-s"])
