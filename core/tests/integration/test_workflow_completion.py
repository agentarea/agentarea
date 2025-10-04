"""Test workflow completion scenarios to identify why workflows never finish."""

import json
import logging
from datetime import timedelta
from uuid import uuid4

import pytest
from agentarea_execution.models import AgentExecutionRequest
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

logger = logging.getLogger(__name__)


@pytest.fixture
def execution_request():
    """Sample execution request for testing."""
    return AgentExecutionRequest(
        agent_id=uuid4(),
        task_id=uuid4(),
        user_id="test-user",
        task_query="Complete a simple test task",
        task_parameters={"success_criteria": ["Task completed successfully"], "max_iterations": 3},
        budget_usd=1.0,
        requires_human_approval=False,
    )


class TestWorkflowCompletion:
    """Test workflow completion scenarios."""

    @pytest.mark.asyncio
    async def test_workflow_completes_immediately_with_task_complete(self, execution_request):
        """Test that workflow completes when LLM calls task_complete immediately."""

        # Track activity calls
        activity_calls = []

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
                            "properties": {
                                "result": {"type": "string", "description": "Final result"}
                            },
                            "required": [],
                        },
                    },
                }
            ]

        async def mock_call_llm(*args, **kwargs):
            activity_calls.append("call_llm")
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

        async def mock_evaluate_goal(*args, **kwargs):
            activity_calls.append("evaluate_goal")
            return {"goal_achieved": False, "final_response": None}

        async def mock_publish_events(*args, **kwargs):
            activity_calls.append("publish_events")
            return True

        # Create test environment
        async with WorkflowEnvironment.start_time_skipping() as env:
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
                # Execute workflow with timeout
                result = await env.client.execute_workflow(
                    AgentExecutionWorkflow.run,
                    execution_request,
                    id=f"test-workflow-{uuid4()}",
                    task_queue="test-queue",
                    execution_timeout=timedelta(
                        seconds=10
                    ),  # Short timeout to catch infinite loops
                )

                # Verify workflow completed
                assert result.success is True
                assert "completed" in result.final_response.lower()
                assert result.reasoning_iterations_used == 1

                # Verify activity call sequence
                logger.info(f"Activity calls: {activity_calls}")
                assert "build_agent_config" in activity_calls
                assert "discover_tools" in activity_calls
                assert "call_llm" in activity_calls
                assert "execute_tool_task_complete" in activity_calls
                # evaluate_goal should be called but shouldn't override success
                assert "evaluate_goal" in activity_calls

    @pytest.mark.asyncio
    async def test_workflow_state_persistence_during_execution(self, execution_request):
        """Test that workflow state persists correctly during execution."""

        state_snapshots = []

        async def mock_build_agent_config(*args, **kwargs):
            return {
                "id": str(execution_request.agent_id),
                "name": "Test Agent",
                "model_id": str(uuid4()),
                "instruction": "Complete tasks",
                "tools_config": {},
                "events_config": {},
                "planning": False,
            }

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

        async def mock_call_llm(*args, **kwargs):
            # Capture state at LLM call time
            return {
                "role": "assistant",
                "content": "Completing task",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "task_complete",
                            "arguments": json.dumps({"result": "Done"}),
                        },
                    }
                ],
                "cost": 0.001,
                "usage": {"total_tokens": 30},
            }

        async def mock_execute_tool(tool_name: str, tool_args: dict, **kwargs):
            if tool_name == "task_complete":
                return {
                    "success": True,
                    "completed": True,
                    "result": "Task completed",
                    "tool_name": "task_complete",
                }
            return {"success": False}

        async def mock_evaluate_goal(*args, **kwargs):
            return {"goal_achieved": False, "final_response": None}

        async def mock_publish_events(*args, **kwargs):
            return True

        async with WorkflowEnvironment() as env:
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
                    execution_timeout=timedelta(seconds=10),
                )

                # Verify final state
                assert result.success is True
                assert result.reasoning_iterations_used == 1

    @pytest.mark.asyncio
    async def test_workflow_with_multiple_tool_calls_before_completion(self, execution_request):
        """Test workflow with multiple tool calls before task_complete."""

        llm_call_count = 0

        async def mock_build_agent_config(*args, **kwargs):
            return {
                "id": str(execution_request.agent_id),
                "name": "Test Agent",
                "model_id": str(uuid4()),
                "instruction": "Complete tasks",
                "tools_config": {},
                "events_config": {},
                "planning": False,
            }

        async def mock_discover_tools(*args, **kwargs):
            return [
                {
                    "type": "function",
                    "function": {
                        "name": "calculate",
                        "description": "Perform calculations",
                        "parameters": {
                            "type": "object",
                            "properties": {"expression": {"type": "string"}},
                            "required": ["expression"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "task_complete",
                        "description": "Mark task as completed",
                        "parameters": {"type": "object", "properties": {}, "required": []},
                    },
                },
            ]

        async def mock_call_llm(*args, **kwargs):
            nonlocal llm_call_count
            llm_call_count += 1

            if llm_call_count == 1:
                # First call - use calculate tool
                return {
                    "role": "assistant",
                    "content": "I'll calculate something first",
                    "tool_calls": [
                        {
                            "id": "call_calc",
                            "type": "function",
                            "function": {
                                "name": "calculate",
                                "arguments": json.dumps({"expression": "2 + 2"}),
                            },
                        }
                    ],
                    "cost": 0.001,
                    "usage": {"total_tokens": 40},
                }
            else:
                # Second call - complete task
                return {
                    "role": "assistant",
                    "content": "Now I'll complete the task",
                    "tool_calls": [
                        {
                            "id": "call_complete",
                            "type": "function",
                            "function": {
                                "name": "task_complete",
                                "arguments": json.dumps(
                                    {"result": "Calculation done, task complete"}
                                ),
                            },
                        }
                    ],
                    "cost": 0.001,
                    "usage": {"total_tokens": 35},
                }

        async def mock_execute_tool(tool_name: str, tool_args: dict, **kwargs):
            if tool_name == "calculate":
                return {"success": True, "result": "4", "tool_name": "calculate"}
            elif tool_name == "task_complete":
                return {
                    "success": True,
                    "completed": True,
                    "result": tool_args.get("result", "Task completed"),
                    "tool_name": "task_complete",
                }
            return {"success": False}

        async def mock_evaluate_goal(*args, **kwargs):
            return {"goal_achieved": False, "final_response": None}

        async def mock_publish_events(*args, **kwargs):
            return True

        async with WorkflowEnvironment() as env:
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

                # Verify workflow completed after 2 iterations
                assert result.success is True
                assert result.reasoning_iterations_used == 2
                assert "calculation" in result.final_response.lower()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v", "-s"])
