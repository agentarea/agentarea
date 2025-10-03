"""Simple test to identify workflow completion issues."""

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
async def test_workflow_completes_with_task_complete():
    """Test that workflow completes when LLM calls task_complete."""

    execution_request = AgentExecutionRequest(
        agent_id=uuid4(),
        task_id=uuid4(),
        user_id="test-user",
        task_query="Complete a simple test task",
        task_parameters={"success_criteria": ["Task completed successfully"], "max_iterations": 3},
        budget_usd=1.0,
        requires_human_approval=False,
    )

    # Track activity calls to debug execution flow
    activity_calls = []

    @activity.defn(name="build_agent_config_activity")
    async def mock_build_agent_config(*args, **kwargs):
        activity_calls.append("build_agent_config")
        return {
            "id": str(execution_request.agent_id),
            "name": "Test Agent",
            "description": "A test agent",
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
                    "parameters": {
                        "type": "object",
                        "properties": {"result": {"type": "string", "description": "Final result"}},
                        "required": [],
                    },
                },
            }
        ]

    @activity.defn(name="call_llm_activity")
    async def mock_call_llm(*args, **kwargs):
        activity_calls.append("call_llm")
        logger.info("Mock LLM called - returning task_complete")
        # LLM immediately calls task_complete
        return {
            "role": "assistant",
            "content": "I'll complete this task now.",
            "tool_calls": [
                {
                    "id": "call_complete",
                    "type": "function",
                    "function": {
                        "name": "task_complete",
                        "arguments": json.dumps({"result": "Task completed successfully"}),
                    },
                }
            ],
            "cost": 0.001,
            "usage": {"total_tokens": 50},
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
        logger.info("Mock evaluate goal called")
        return {"goal_achieved": False, "final_response": None}

    @activity.defn(name="publish_workflow_events_activity")
    async def mock_publish_events(*args, **kwargs):
        activity_calls.append("publish_events")
        return True

    # Create test environment
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
            logger.info("Starting workflow execution test")

            # Execute workflow with timeout
            result = await env.client.execute_workflow(
                AgentExecutionWorkflow.run,
                execution_request,
                id=f"test-workflow-{uuid4()}",
                task_queue="test-queue",
                execution_timeout=timedelta(seconds=10),  # Short timeout to catch infinite loops
            )

            logger.info(f"Workflow completed with result: {result}")
            logger.info(f"Activity calls: {activity_calls}")

            # Verify workflow completed
            assert result.success is True, f"Expected success=True, got {result.success}"
            assert "completed" in result.final_response.lower(), (
                f"Expected 'completed' in response: {result.final_response}"
            )
            assert result.reasoning_iterations_used == 1, (
                f"Expected 1 iteration, got {result.reasoning_iterations_used}"
            )

            # Verify activity call sequence
            assert "build_agent_config" in activity_calls
            assert "discover_tools" in activity_calls
            assert "call_llm" in activity_calls
            assert "execute_tool_task_complete" in activity_calls
    finally:
        await env.shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v", "-s"])
