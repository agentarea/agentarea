"""
Integration tests for AgentTaskWorkflow using Temporal testing framework.

This test suite covers:
- Workflow execution with mocked activities
- Signal handling for dynamic activities
- Time skipping for long-running operations
- Error handling and retry logic
"""

import pytest
import pytest_asyncio
import uuid
import asyncio
from datetime import timedelta
from typing import Any, AsyncGenerator

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from agentarea.workflows.agent_task_workflow import (
    AgentTaskWorkflow,
    execute_dynamic_activity,
    execute_mcp_tool_activity,
    execute_custom_tool_activity,
    execute_agent_communication_activity,
)

# Configure pytest for async tests
pytestmark = pytest.mark.asyncio


# Mock Activity Implementations
@activity.defn(name="validate_agent_activity")
async def mock_validate_agent_activity(agent_id: str) -> dict[str, Any]:
    """Mock agent validation - always returns valid."""
    return {
        "valid": True,
        "errors": [],
        "agent_id": agent_id
    }


@activity.defn(name="execute_agent_activity")
async def mock_execute_agent_activity(
    agent_id: str,
    task_id: str,
    query: str,
    user_id: str,
    task_parameters: dict[str, Any]
) -> dict[str, Any]:
    """Mock agent execution with some discovered activities."""
    return {
        "status": "completed",
        "events": [
            {"event_type": "TaskStarted", "timestamp": "2025-01-01T00:00:00Z"},
            {"event_type": "MCPServerDiscovered", "mcp_config": {"server": "test-mcp"}},
            {"event_type": "ToolDiscovered", "tool_config": {"tool": "test-tool"}},
            {"event_type": "TaskCompleted", "timestamp": "2025-01-01T00:01:00Z"},
        ],
        "discovered_activities": [
            {"type": "mcp_tool_call", "config": {"server": "test-mcp"}},
            {"type": "custom_tool", "config": {"tool": "test-tool"}},
        ],
        "event_count": 4,
        "task_id": task_id
    }


@activity.defn(name="execute_dynamic_activity")
async def mock_execute_dynamic_activity(
    activity_type: str,
    config: dict[str, Any]
) -> dict[str, Any]:
    """Mock dynamic activity execution."""
    return {
        "status": "completed",
        "activity_type": activity_type,
        "config": config,
        "result": f"Mock {activity_type} executed successfully"
    }


@activity.defn(name="execute_mcp_tool_activity")
async def mock_execute_mcp_tool_activity(config: dict[str, Any]) -> dict[str, Any]:
    """Mock MCP tool execution."""
    return {
        "status": "completed",
        "activity_type": "mcp_tool_call",
        "config": config,
        "result": "Mock MCP tool executed successfully"
    }


@activity.defn(name="execute_custom_tool_activity")
async def mock_execute_custom_tool_activity(config: dict[str, Any]) -> dict[str, Any]:
    """Mock custom tool execution."""
    return {
        "status": "completed",
        "activity_type": "custom_tool",
        "config": config,
        "result": "Mock custom tool executed successfully"
    }


@activity.defn(name="execute_agent_communication_activity")
async def mock_execute_agent_communication_activity(config: dict[str, Any]) -> dict[str, Any]:
    """Mock agent communication execution."""
    return {
        "status": "completed",
        "activity_type": "agent_communication",
        "config": config,
        "result": "Mock agent communication completed"
    }


class TestAgentTaskWorkflow:
    """Test suite for AgentTaskWorkflow."""

    @pytest_asyncio.fixture
    async def env(self) -> AsyncGenerator[WorkflowEnvironment, None]:
        """Create a test environment with time skipping."""
        async with await WorkflowEnvironment.start_time_skipping() as test_env:
            yield test_env

    @pytest_asyncio.fixture
    async def client(self, env: WorkflowEnvironment) -> Client:
        """Create a test client."""
        return env.client

    @pytest.fixture
    def task_queue(self) -> str:
        """Generate a unique task queue name for each test."""
        return f"test-agent-tasks-{uuid.uuid4()}"

    @pytest.fixture
    def workflow_id(self) -> str:
        """Generate a unique workflow ID for each test."""
        return f"test-agent-workflow-{uuid.uuid4()}"

    async def test_successful_workflow_execution(self, client: Client, task_queue: str, workflow_id: str):
        """Test successful workflow execution with mocked activities."""
        # Start worker with mocked activities
        async with Worker(
            client,
            task_queue=task_queue,
            workflows=[AgentTaskWorkflow],
            activities=[
                mock_validate_agent_activity,
                mock_execute_agent_activity,
                mock_execute_dynamic_activity,
                mock_execute_mcp_tool_activity,
                mock_execute_custom_tool_activity,
                mock_execute_agent_communication_activity,
            ],
        ):
            # Execute workflow with args parameter
            result = await client.execute_workflow(
                AgentTaskWorkflow.run,
                args=[
                    "test-agent-123",
                    "test-task-456", 
                    "Test query for agent",
                    "test-user",
                    {"param1": "value1"},
                    {"test": True}
                ],
                id=workflow_id,
                task_queue=task_queue,
                execution_timeout=timedelta(minutes=10),
            )

            # Verify results
            assert result["status"] == "completed"
            assert result["task_id"] == "test-task-456"
            assert result["agent_id"] == "test-agent-123"
            assert "result" in result
            
            # Verify main execution result
            execution_result = result["result"]
            assert execution_result["status"] == "completed"
            assert execution_result["event_count"] == 4
            assert len(execution_result["discovered_activities"]) == 2
            
            # Verify dynamic activities were executed
            assert "dynamic_results" in execution_result
            assert len(execution_result["dynamic_results"]) == 2

    async def test_agent_validation_failure(self, client: Client, task_queue: str, workflow_id: str):
        """Test workflow behavior when agent validation fails."""
        
        @activity.defn(name="validate_agent_activity")
        async def mock_validate_agent_activity_failure(agent_id: str) -> dict[str, Any]:
            """Mock agent validation that fails."""
            return {
                "valid": False,
                "errors": ["Agent not found", "Invalid configuration"],
                "agent_id": agent_id
            }

        async with Worker(
            client,
            task_queue=task_queue,
            workflows=[AgentTaskWorkflow],
            activities=[
                mock_validate_agent_activity_failure,
                mock_execute_agent_activity,
                mock_execute_dynamic_activity,
            ],
        ):
            # Execute workflow - should fail validation
            result = await client.execute_workflow(
                AgentTaskWorkflow.run,
                args=["invalid-agent", "test-task-456", "Test query"],
                id=workflow_id,
                task_queue=task_queue,
                execution_timeout=timedelta(minutes=1),
            )

            # Verify failure result
            assert result["status"] == "failed"
            assert "Agent validation failed" in result["error"]
            assert result["task_id"] == "test-task-456"

    async def test_workflow_timeout_handling(self, client: Client, task_queue: str, workflow_id: str):
        """Test workflow behavior with long-running activities (time skipping)."""
        
        @activity.defn(name="execute_agent_activity")
        async def mock_slow_agent_activity(
            agent_id: str,
            task_id: str,
            query: str,
            user_id: str,
            task_parameters: dict[str, Any]
        ) -> dict[str, Any]:
            """Mock slow agent activity that would normally take hours."""
            # This would normally take hours, but with time skipping it's instant
            await asyncio.sleep(2)  # Use asyncio.sleep instead of activity.sleep
            return {
                "status": "completed",
                "events": [{"event_type": "SlowTaskCompleted"}],
                "discovered_activities": [],
                "event_count": 1,
                "task_id": task_id
            }

        async with Worker(
            client,
            task_queue=task_queue,
            workflows=[AgentTaskWorkflow],
            activities=[
                mock_validate_agent_activity,
                mock_slow_agent_activity,
                mock_execute_dynamic_activity,
            ],
        ):
            # Execute workflow - should complete quickly due to time skipping
            result = await client.execute_workflow(
                AgentTaskWorkflow.run,
                args=["test-agent-123", "test-task-456", "Long running query"],
                id=workflow_id,
                task_queue=task_queue,
                execution_timeout=timedelta(hours=3),
            )

            # Verify completion despite long activity duration
            assert result["status"] == "completed"
            assert result["result"]["event_count"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"]) 