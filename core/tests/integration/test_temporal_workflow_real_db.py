"""
Real Database Integration Tests for Temporal Workflows

This test suite tests the actual AgentTaskWorkflow with:
- Real database connections
- Real activities (not mocked)
- Real services and repositories
- Actual agent execution flow

These tests require:
- Database to be running and accessible
- Redis to be running (or will fallback to TestEventBroker)
- Temporal server to be running
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

# Import database and models for test setup
from agentarea.api.deps.database import get_db_session
from agentarea.modules.agents.domain.models import Agent
from agentarea.modules.agents.infrastructure.repository import AgentRepository
from agentarea.modules.llm.domain.models import LLMModel, LLMModelInstance
from agentarea.modules.llm.infrastructure.llm_model_instance_repository import (
    LLMModelInstanceRepository,
)
from agentarea.modules.llm.infrastructure.llm_model_repository import LLMModelRepository
from agentarea.workflows.agent_task_workflow import (
    AgentTaskWorkflow,
    execute_agent_activity,
    execute_agent_communication_activity,
    execute_custom_tool_activity,
    execute_dynamic_activity,
    execute_mcp_tool_activity,
    validate_agent_activity,
)

# Configure pytest for async tests
pytestmark = pytest.mark.asyncio


class TestTemporalWorkflowRealDB:
    """Integration tests for Temporal workflows with real database."""

    @pytest_asyncio.fixture
    async def env(self) -> AsyncGenerator[WorkflowEnvironment, None]:
        """Create test environment with time skipping."""
        async with await WorkflowEnvironment.start_time_skipping() as test_env:
            yield test_env

    @pytest_asyncio.fixture
    async def client(self, env: WorkflowEnvironment) -> Client:
        """Get test client."""
        return env.client

    @pytest.fixture
    def task_queue(self) -> str:
        """Unique task queue per test."""
        return f"real-db-test-{uuid.uuid4()}"

    @pytest.fixture
    def workflow_id(self) -> str:
        """Unique workflow ID per test."""
        return f"real-db-workflow-{uuid.uuid4()}"

    @pytest_asyncio.fixture
    async def test_agent_data(self) -> dict[str, Any]:
        """Create test agent data in the database."""
        test_data = {}

        async with get_db_session() as db_session:
            # Create repositories
            llm_model_repo = LLMModelRepository(db_session)
            llm_instance_repo = LLMModelInstanceRepository(db_session)
            agent_repo = AgentRepository(db_session)

            # Create a test LLM model
            llm_model = LLMModel(
                name="test-model-workflow",
                description="Test model for workflow testing",
                provider="ollama",
                model_type="chat",
                endpoint_url="http://localhost:11434",
                context_window=4096,
                is_public=True,
            )
            await llm_model_repo.create(llm_model)
            test_data["llm_model_id"] = str(llm_model.id)

            # Create a test LLM model instance
            llm_instance = LLMModelInstance(
                model_id=llm_model.id,
                name="test-instance-workflow",
                description="Test instance for workflow testing",
                api_key="test-key",
                is_public=True,
            )
            await llm_instance_repo.create(llm_instance)
            test_data["llm_instance_id"] = str(llm_instance.id)

            # Create a test agent
            agent = Agent(
                name="test-agent-workflow",
                description="Test agent for workflow testing",
                instruction="You are a test agent for workflow integration testing.",
                model_id=llm_instance.id,
                planning=False,
            )
            await agent_repo.create(agent)
            test_data["agent_id"] = str(agent.id)

            await db_session.commit()

        return test_data

    async def test_workflow_with_real_database_validation_success(
        self, client: Client, task_queue: str, workflow_id: str, test_agent_data: dict[str, Any]
    ):
        """Test workflow execution with real database - successful validation."""

        # Start worker with REAL activities (not mocked)
        async with Worker(
            client,
            task_queue=task_queue,
            workflows=[AgentTaskWorkflow],
            activities=[
                validate_agent_activity,  # Real activity
                execute_agent_activity,  # Real activity
                execute_dynamic_activity,
                execute_mcp_tool_activity,
                execute_custom_tool_activity,
                execute_agent_communication_activity,
            ],
            debug_mode=True,  # Отключает sandbox для избежания SQLAlchemy конфликтов
        ):
            # Execute workflow with real agent ID from database
            result = await client.execute_workflow(
                AgentTaskWorkflow.run,
                args=[
                    test_agent_data["agent_id"],  # Real agent ID
                    f"test-task-{uuid.uuid4()}",
                    "Hello, can you help me with a simple test?",
                    "test-user",
                    {"test_param": "test_value"},
                    {"test": True},
                ],
                id=workflow_id,
                task_queue=task_queue,
                execution_timeout=timedelta(minutes=10),
            )

            # Verify results
            assert result["status"] == "completed"
            assert result["agent_id"] == test_agent_data["agent_id"]
            assert "result" in result

            # Verify the validation actually happened with real database
            execution_result = result["result"]
            assert execution_result["status"] == "completed"
            assert "events" in execution_result
            assert execution_result["event_count"] >= 0

    async def test_workflow_with_invalid_agent_id(
        self, client: Client, task_queue: str, workflow_id: str
    ):
        """Test workflow with invalid agent ID - should fail validation."""

        async with Worker(
            client,
            task_queue=task_queue,
            workflows=[AgentTaskWorkflow],
            activities=[
                validate_agent_activity,  # Real activity
                execute_agent_activity,  # Real activity
                execute_dynamic_activity,
                execute_mcp_tool_activity,
                execute_custom_tool_activity,
                execute_agent_communication_activity,
            ],
            debug_mode=True,  # Отключает sandbox для избежания SQLAlchemy конфликтов
        ):
            # Use invalid agent ID
            invalid_agent_id = str(uuid.uuid4())

            result = await client.execute_workflow(
                AgentTaskWorkflow.run,
                args=[
                    invalid_agent_id,
                    f"test-task-{uuid.uuid4()}",
                    "This should fail validation",
                    "test-user",
                    {},
                    {},
                ],
                id=workflow_id,
                task_queue=task_queue,
                execution_timeout=timedelta(minutes=5),
            )

            # Should fail at validation stage
            assert result["status"] == "failed"
            assert "Agent validation failed" in result.get("error", "")

    async def test_real_activity_validate_agent_directly(self, test_agent_data: dict[str, Any]):
        """Test the validate_agent_activity directly with real database."""

        # Test with valid agent
        result = await validate_agent_activity(test_agent_data["agent_id"])

        assert isinstance(result, dict)
        assert "valid" in result
        assert "errors" in result
        assert "agent_id" in result
        assert result["agent_id"] == test_agent_data["agent_id"]

        # For a properly configured agent, validation should pass
        if result["valid"]:
            assert len(result["errors"]) == 0
        else:
            # If validation fails, there should be specific errors
            assert len(result["errors"]) > 0
            print(f"Validation errors: {result['errors']}")

    async def test_real_activity_validate_agent_invalid_id(self):
        """Test validate_agent_activity with invalid agent ID."""

        invalid_agent_id = str(uuid.uuid4())

        result = await validate_agent_activity(invalid_agent_id)

        assert isinstance(result, dict)
        assert result["valid"] is False
        assert len(result["errors"]) > 0
        assert result["agent_id"] == invalid_agent_id

    async def test_real_activity_execute_agent_basic(self, test_agent_data: dict[str, Any]):
        """Test execute_agent_activity directly with real database."""

        task_id = f"direct-test-{uuid.uuid4()}"

        result = await execute_agent_activity(
            agent_id=test_agent_data["agent_id"],
            task_id=task_id,
            query="Hello, this is a test query for direct activity testing.",
            user_id="test-user",
            task_parameters={"direct_test": True},
        )

        assert isinstance(result, dict)
        assert result["status"] == "completed"
        assert result["task_id"] == task_id
        assert "events" in result
        assert "discovered_activities" in result
        assert "event_count" in result
        assert isinstance(result["events"], list)
        assert isinstance(result["discovered_activities"], list)
        assert result["event_count"] >= 0

    async def test_database_connection_in_activities(self):
        """Test that database connections work properly in activities."""

        # This test verifies that get_db_session() works as expected
        async with get_db_session() as db_session:
            # Verify we can execute a simple query using SQLAlchemy text
            result = await db_session.execute(text("SELECT 1 as test_value"))
            row = result.fetchone()
            assert row is not None
            assert row[0] == 1

    @pytest_asyncio.fixture(scope="function")
    async def cleanup_test_data(self, test_agent_data: dict[str, Any]):
        """Cleanup test data after each test."""
        yield

        # Cleanup after test
        try:
            async with get_db_session() as db_session:
                # Clean up in reverse order due to foreign keys
                agent_repo = AgentRepository(db_session)
                llm_instance_repo = LLMModelInstanceRepository(db_session)
                llm_model_repo = LLMModelRepository(db_session)

                # Delete agent
                agent_id = uuid.UUID(test_agent_data["agent_id"])
                await agent_repo.delete(agent_id)

                # Delete LLM instance
                llm_instance_id = uuid.UUID(test_agent_data["llm_instance_id"])
                await llm_instance_repo.delete(llm_instance_id)

                # Delete LLM model
                llm_model_id = uuid.UUID(test_agent_data["llm_model_id"])
                await llm_model_repo.delete(llm_model_id)

                await db_session.commit()
        except Exception as e:
            print(f"Cleanup error (non-critical): {e}")


if __name__ == "__main__":
    # Run specific test
    pytest.main([__file__, "-v", "-s"])
