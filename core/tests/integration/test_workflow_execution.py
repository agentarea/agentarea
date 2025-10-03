"""Integration tests for agent execution workflow.

Tests the complete workflow execution with real Temporal worker to identify
why workflows never finish.
"""

import json
import logging
from datetime import timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from agentarea_execution.interfaces import ActivityDependencies
from agentarea_execution.models import AgentExecutionRequest, AgentExecutionResult
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

logger = logging.getLogger(__name__)


class MockSecretManager:
    """Mock secret manager for testing."""

    async def get_secret(self, secret_name: str) -> str:
        return f"mock-api-key-{secret_name}"


class MockEventBroker:
    """Mock event broker for testing."""

    def __init__(self):
        self.published_events = []

    async def publish(self, event):
        self.published_events.append(event)
        logger.info(f"Mock published event: {event}")


@pytest.fixture
def mock_dependencies():
    """Create mock dependencies for testing."""
    deps = MagicMock(spec=ActivityDependencies)
    deps.secret_manager = MockSecretManager()
    deps.event_broker = MockEventBroker()
    return deps


@pytest.fixture
def sample_agent_config():
    """Sample agent configuration for testing."""
    return {
        "id": str(uuid4()),
        "name": "Test Agent",
        "description": "A test agent",
        "instruction": "You are a helpful test agent. Complete tasks efficiently.",
        "model_id": str(uuid4()),
        "tools_config": {},
        "events_config": {},
        "planning": False,
    }


@pytest.fixture
def sample_tools():
    """Sample tools configuration for testing."""
    return [
        {
            "type": "function",
            "function": {
                "name": "task_complete",
                "description": "Mark task as completed when you have finished the task successfully",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "result": {
                            "type": "string",
                            "description": "Final result or summary of what was accomplished",
                        }
                    },
                    "required": [],
                },
            },
        }
    ]


@pytest.fixture
def execution_request():
    """Sample execution request for testing."""
    return AgentExecutionRequest(
        agent_id=uuid4(),
        task_id=uuid4(),
        user_id="test-user",
        task_query="Complete a simple test task",
        task_parameters={"success_criteria": ["Task completed successfully"], "max_iterations": 5},
        budget_usd=1.0,
        requires_human_approval=False,
    )


class TestWorkflowExecution:
    """Test workflow execution scenarios."""

    @pytest.mark.asyncio
    async def test_workflow_completes_with_immediate_task_complete(
        self, mock_dependencies, sample_agent_config, sample_tools, execution_request
    ):
        """Test workflow completes when LLM immediately calls task_complete."""

        # Mock activities to simulate immediate completion
        async def mock_build_agent_config(*args, **kwargs):
            return sample_agent_config

        async def mock_discover_tools(*args, **kwargs):
            return sample_tools

        async def mock_call_llm(*args, **kwargs):
            # Simulate LLM calling task_complete immediately
            return {
                "role": "assistant",
                "content": "I'll complete this task now.",
                "tool_calls": [
                    {
                        "id": "call_1",
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
            if tool_name == "task_complete":
                return {
                    "success": True,
                    "completed": True,
                    "result": tool_args.get("result", "Task completed"),
                    "tool_name": "task_complete",
                }
            return {"success": False, "result": "Unknown tool"}

        async def mock_publish_events(*args, **kwargs):
            return True

        # Create test environment
        async with WorkflowEnvironment() as env:
            # Create activities with mocks
            activities = [
                mock_build_agent_config,
                mock_discover_tools,
                mock_call_llm,
                mock_execute_tool,
                mock_publish_events,
            ]

            # Start worker
            async with Worker(
                env.client,
                task_queue="test-queue",
                workflows=[AgentExecutionWorkflow],
                activities=activities,
            ):
                # Execute workflow
                result = await env.client.execute_workflow(
                    AgentExecutionWorkflow.run,
                    execution_request,
                    id=f"test-workflow-{uuid4()}",
                    task_queue="test-queue",
                    execution_timeout=timedelta(seconds=30),
                )

                # Verify workflow completed successfully
                assert isinstance(result, AgentExecutionResult)
                assert result.success is True
                assert "completed" in result.final_response.lower()
                assert result.reasoning_iterations_used >= 1

    @pytest.mark.asyncio
    async def test_workflow_completes_after_multiple_iterations(
        self, mock_dependencies, sample_agent_config, sample_tools, execution_request
    ):
        """Test workflow completes after multiple iterations."""

        call_count = 0

        async def mock_build_agent_config(*args, **kwargs):
            return sample_agent_config

        async def mock_discover_tools(*args, **kwargs):
            return sample_tools

        async def mock_call_llm(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # First call - just thinking
                return {
                    "role": "assistant",
                    "content": "I need to analyze this task first.",
                    "tool_calls": None,
                    "cost": 0.001,
                    "usage": {"total_tokens": 30},
                }
            elif call_count == 2:
                # Second call - still working
                return {
                    "role": "assistant",
                    "content": "Let me work on this step by step.",
                    "tool_calls": None,
                    "cost": 0.001,
                    "usage": {"total_tokens": 40},
                }
            else:
                # Third call - complete the task
                return {
                    "role": "assistant",
                    "content": "Now I'll complete the task.",
                    "tool_calls": [
                        {
                            "id": "call_complete",
                            "type": "function",
                            "function": {
                                "name": "task_complete",
                                "arguments": json.dumps(
                                    {"result": "Task completed after analysis"}
                                ),
                            },
                        }
                    ],
                    "cost": 0.001,
                    "usage": {"total_tokens": 45},
                }

        async def mock_execute_tool(tool_name: str, tool_args: dict, **kwargs):
            if tool_name == "task_complete":
                return {
                    "success": True,
                    "completed": True,
                    "result": tool_args.get("result", "Task completed"),
                    "tool_name": "task_complete",
                }
            return {"success": False, "result": "Unknown tool"}

        async def mock_publish_events(*args, **kwargs):
            return True

        # Create test environment
        async with WorkflowEnvironment() as env:
            activities = [
                mock_build_agent_config,
                mock_discover_tools,
                mock_call_llm,
                mock_execute_tool,
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
                    execution_timeout=timedelta(seconds=30),
                )

                # Verify workflow completed after multiple iterations
                assert isinstance(result, AgentExecutionResult)
                assert result.success is True
                assert result.reasoning_iterations_used == 3
                assert "analysis" in result.final_response.lower()

    @pytest.mark.asyncio
    async def test_workflow_stops_at_max_iterations(
        self, mock_dependencies, sample_agent_config, sample_tools, execution_request
    ):
        """Test workflow stops when max iterations reached."""

        # Set low max iterations
        execution_request.task_parameters["max_iterations"] = 2

        async def mock_build_agent_config(*args, **kwargs):
            return sample_agent_config

        async def mock_discover_tools(*args, **kwargs):
            return sample_tools

        async def mock_call_llm(*args, **kwargs):
            # Never call task_complete - just keep thinking
            return {
                "role": "assistant",
                "content": "I'm still working on this task...",
                "tool_calls": None,
                "cost": 0.001,
                "usage": {"total_tokens": 30},
            }

        async def mock_execute_tool(tool_name: str, tool_args: dict, **kwargs):
            return {"success": False, "result": "Should not be called"}

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
                    execution_timeout=timedelta(seconds=30),
                )

                # Verify workflow stopped at max iterations
                assert isinstance(result, AgentExecutionResult)
                assert result.success is False  # Should not be successful
                assert result.reasoning_iterations_used == 2  # Should hit max iterations

    @pytest.mark.asyncio
    async def test_workflow_stops_on_budget_exceeded(
        self, mock_dependencies, sample_agent_config, sample_tools, execution_request
    ):
        """Test workflow stops when budget is exceeded."""

        # Set very low budget
        execution_request.budget_usd = 0.001

        async def mock_build_agent_config(*args, **kwargs):
            return sample_agent_config

        async def mock_discover_tools(*args, **kwargs):
            return sample_tools

        async def mock_call_llm(*args, **kwargs):
            # Return high cost to exceed budget
            return {
                "role": "assistant",
                "content": "This is an expensive call.",
                "tool_calls": None,
                "cost": 0.01,  # Exceeds budget of 0.001
                "usage": {"total_tokens": 1000},
            }

        async def mock_execute_tool(tool_name: str, tool_args: dict, **kwargs):
            return {"success": False, "result": "Should not be called"}

        async def mock_publish_events(*args, **kwargs):
            return True

        async with WorkflowEnvironment() as env:
            activities = [
                mock_build_agent_config,
                mock_discover_tools,
                mock_call_llm,
                mock_execute_tool,
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
                    execution_timeout=timedelta(seconds=30),
                )

                # Verify workflow stopped due to budget
                assert isinstance(result, AgentExecutionResult)
                assert result.success is False
                assert result.total_cost > execution_request.budget_usd


class TestWorkflowStateManagement:
    """Test workflow state management and termination conditions."""

    def test_workflow_state_success_flag(self):
        """Test that workflow success flag is properly managed."""
        from agentarea_execution.workflows.agent_execution_workflow import (
            AgentExecutionState,
            AgentGoal,
        )

        # Create state
        state = AgentExecutionState()
        state.goal = AgentGoal(
            id="test",
            description="Test goal",
            success_criteria=["Complete task"],
            max_iterations=5,
            requires_human_approval=False,
            context={},
        )

        # Initially not successful
        assert state.success is False

        # Set success
        state.success = True
        assert state.success is True

    def test_termination_conditions(self):
        """Test all termination conditions."""
        from agentarea_execution.workflows.agent_execution_workflow import (
            AgentExecutionState,
            AgentExecutionWorkflow,
            AgentGoal,
        )
        from agentarea_execution.workflows.helpers import BudgetTracker

        workflow_instance = AgentExecutionWorkflow()
        workflow_instance.state = AgentExecutionState()
        workflow_instance.state.goal = AgentGoal(
            id="test",
            description="Test goal",
            success_criteria=["Complete task"],
            max_iterations=3,
            requires_human_approval=False,
            context={},
        )
        workflow_instance.budget_tracker = BudgetTracker(1.0)

        # Test 1: Success condition
        workflow_instance.state.success = True
        should_continue, reason = workflow_instance._should_continue_execution()
        assert should_continue is False
        assert "achieved" in reason.lower()

        # Reset
        workflow_instance.state.success = False

        # Test 2: Max iterations
        workflow_instance.state.current_iteration = 3
        should_continue, reason = workflow_instance._should_continue_execution()
        assert should_continue is False
        assert "maximum iterations" in reason.lower()

        # Reset
        workflow_instance.state.current_iteration = 1

        # Test 3: Budget exceeded
        workflow_instance.budget_tracker.cost = 2.0  # Exceeds budget of 1.0
        should_continue, reason = workflow_instance._should_continue_execution()
        assert should_continue is False
        assert "budget exceeded" in reason.lower()

        # Reset
        workflow_instance.budget_tracker.cost = 0.1

        # Test 4: Should continue
        should_continue, reason = workflow_instance._should_continue_execution()
        assert should_continue is True
        assert "continue" in reason.lower()


if __name__ == "__main__":
    # Run tests with detailed logging
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v", "-s"])
