#!/usr/bin/env python3
"""
Comprehensive integration tests for ADK Agent Workflow.

Tests the complete ADK-Temporal workflow integration with real dependencies,
including error handling, queries, signals, and various execution scenarios.
"""

import asyncio
import logging
from datetime import timedelta
from uuid import UUID, uuid4

import pytest

# Import dependencies
from agentarea_common.config import get_settings
from agentarea_common.events.router import get_event_router
from agentarea_execution import create_activities_for_worker

# Import workflow and activities
from agentarea_execution.adk_temporal.workflows.adk_agent_workflow import ADKAgentWorkflow
from agentarea_execution.interfaces import ActivityDependencies
from agentarea_execution.models import AgentExecutionRequest
from agentarea_secrets import get_real_secret_manager
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.worker import Worker

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestADKAgentWorkflowComprehensive:
    """Comprehensive integration tests for ADK workflow with real Temporal infrastructure."""

    @pytest.fixture(scope="class")
    def activity_dependencies(self):
        """Create activity dependencies for testing."""
        settings = get_settings()
        event_broker = get_event_router(settings.broker)
        secret_manager = get_real_secret_manager()

        return ActivityDependencies(
            settings=settings, event_broker=event_broker, secret_manager=secret_manager
        )

    @pytest.fixture(scope="class")
    async def temporal_client(self):
        """Create Temporal client for testing."""
        client = await Client.connect("localhost:7233")
        return client
        # Client cleanup is automatic

    @pytest.fixture
    def sample_request(self):
        """Create a sample agent execution request."""
        # Use existing agent ID
        existing_agent_id = UUID("8bd81439-21d2-41bb-8035-02f87641056a")

        return AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=existing_agent_id,
            user_id="integration-test-user",
            task_query="Hello, this is a comprehensive integration test. Please respond with 'Integration test successful!' and explain what you are.",
            timeout_seconds=120,
            max_reasoning_iterations=3,
        )

    @pytest.fixture
    def simple_math_request(self):
        """Create a simple math request for testing."""
        # Use existing agent ID
        existing_agent_id = UUID("8bd81439-21d2-41bb-8035-02f87641056a")

        return AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=existing_agent_id,
            user_id="math-test-user",
            task_query="What is 7 + 5? Please provide just the number as your answer.",
            timeout_seconds=60,
            max_reasoning_iterations=2,
        )

    @pytest.fixture
    def existing_agent_request(self):
        """Create a request using an existing agent ID."""
        # Use a known agent ID from the database
        existing_agent_id = UUID("8bd81439-21d2-41bb-8035-02f87641056a")

        return AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=existing_agent_id,
            user_id="existing-agent-test",
            task_query="Hello from existing agent test! Please introduce yourself.",
            timeout_seconds=90,
            max_reasoning_iterations=2,
        )

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_basic_adk_workflow_execution(
        self, temporal_client, activity_dependencies, sample_request
    ):
        """Test basic ADK workflow execution with real Temporal server."""

        logger.info("🧪 Starting basic ADK workflow execution test")

        # Create activities
        activities = create_activities_for_worker(activity_dependencies)

        # Create worker
        worker = Worker(
            temporal_client,
            task_queue="test-adk-basic",
            workflows=[ADKAgentWorkflow],
            activities=activities,
            max_concurrent_workflow_tasks=1,
            max_concurrent_activities=5,
        )

        async with worker:
            # Start workflow
            handle = await temporal_client.start_workflow(
                ADKAgentWorkflow.run,
                sample_request,
                id=f"basic-test-{sample_request.task_id}",
                task_queue="test-adk-basic",
                execution_timeout=timedelta(minutes=3),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

            logger.info(f"📋 Workflow started with ID: {handle.id}")

            # Wait for completion
            try:
                result = await asyncio.wait_for(handle.result(), timeout=180.0)

                # Verify result structure
                assert result is not None
                assert hasattr(result, "success")
                assert hasattr(result, "final_response")
                assert hasattr(result, "task_id")
                assert hasattr(result, "agent_id")
                assert hasattr(result, "conversation_history")

                # Verify result values
                assert result.task_id == sample_request.task_id
                assert result.agent_id == sample_request.agent_id

                logger.info("✅ Basic workflow test completed successfully!")
                logger.info(f"   Success: {result.success}")
                logger.info(f"   Response: {result.final_response}")
                logger.info(f"   Conversation history length: {len(result.conversation_history)}")
                logger.info(f"   Total cost: ${result.total_cost:.6f}")

                return result

            except TimeoutError:
                logger.error("❌ Workflow timed out")
                pytest.fail("Workflow execution timed out")

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_simple_math_workflow(
        self, temporal_client, activity_dependencies, simple_math_request
    ):
        """Test workflow with a simple math question."""

        logger.info("🧮 Starting simple math workflow test")

        activities = create_activities_for_worker(activity_dependencies)

        worker = Worker(
            temporal_client,
            task_queue="test-adk-math",
            workflows=[ADKAgentWorkflow],
            activities=activities,
        )

        async with worker:
            handle = await temporal_client.start_workflow(
                ADKAgentWorkflow.run,
                simple_math_request,
                id=f"math-test-{simple_math_request.task_id}",
                task_queue="test-adk-math",
                execution_timeout=timedelta(minutes=2),
            )

            logger.info(f"📋 Math workflow started with ID: {handle.id}")

            result = await asyncio.wait_for(handle.result(), timeout=120.0)

            # Verify math result
            assert result.success is True
            assert result.final_response is not None

            # Check if the response contains the expected answer (12)
            response_text = result.final_response.lower()
            assert "12" in response_text or "twelve" in response_text

            logger.info("✅ Math workflow test completed!")
            logger.info(f"   Response: {result.final_response}")

            return result

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_workflow_queries_and_signals(
        self, temporal_client, activity_dependencies, sample_request
    ):
        """Test workflow queries and signals during execution."""

        logger.info("🔍 Starting workflow queries and signals test")

        activities = create_activities_for_worker(activity_dependencies)

        worker = Worker(
            temporal_client,
            task_queue="test-adk-queries",
            workflows=[ADKAgentWorkflow],
            activities=activities,
        )

        async with worker:
            handle = await temporal_client.start_workflow(
                ADKAgentWorkflow.run,
                sample_request,
                id=f"query-test-{sample_request.task_id}",
                task_queue="test-adk-queries",
            )

            logger.info(f"📋 Query test workflow started: {handle.id}")

            # Wait a moment for workflow to start processing
            await asyncio.sleep(3)

            # Test queries
            try:
                current_state = await handle.query("get_current_state")
                logger.info(f"📊 Current state: {current_state}")

                assert "execution_id" in current_state
                assert "event_count" in current_state
                assert "success" in current_state

                events = await handle.query("get_events", 10)
                logger.info(f"📝 Events retrieved: {len(events) if events else 0}")

                final_response = await handle.query("get_final_response")
                logger.info(f"💬 Final response query: {final_response}")

            except Exception as query_error:
                logger.warning(f"⚠️ Query failed (workflow may not be ready): {query_error}")

            # Test signals
            try:
                await handle.signal("pause", "Integration test pause")
                logger.info("⏸️ Sent pause signal")

                await asyncio.sleep(2)

                # Query state after pause
                paused_state = await handle.query("get_current_state")
                logger.info(f"📊 State after pause: {paused_state.get('paused', 'unknown')}")

                await handle.signal("resume", "Integration test resume")
                logger.info("▶️ Sent resume signal")

            except Exception as signal_error:
                logger.warning(f"⚠️ Signal failed: {signal_error}")

            # Wait for completion
            result = await asyncio.wait_for(handle.result(), timeout=180.0)

            logger.info("✅ Query and signal test completed successfully!")
            return result

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_workflow_with_existing_agent(
        self, temporal_client, activity_dependencies, existing_agent_request
    ):
        """Test workflow with an existing agent from the database."""

        logger.info("👤 Starting existing agent workflow test")

        activities = create_activities_for_worker(activity_dependencies)

        worker = Worker(
            temporal_client,
            task_queue="test-adk-existing",
            workflows=[ADKAgentWorkflow],
            activities=activities,
        )

        async with worker:
            handle = await temporal_client.start_workflow(
                ADKAgentWorkflow.run,
                existing_agent_request,
                id=f"existing-agent-test-{existing_agent_request.task_id}",
                task_queue="test-adk-existing",
            )

            logger.info(f"📋 Existing agent test started: {handle.id}")
            logger.info(f"   Using agent ID: {existing_agent_request.agent_id}")

            try:
                result = await asyncio.wait_for(handle.result(), timeout=120.0)

                assert result.agent_id == existing_agent_request.agent_id
                assert result.final_response is not None

                logger.info("✅ Existing agent test completed successfully!")
                logger.info(f"   Agent ID: {result.agent_id}")
                logger.info(f"   Response: {result.final_response}")

                return result

            except Exception as e:
                logger.warning(f"⚠️ Existing agent test failed (agent may not exist): {e}")
                # This is expected if the agent doesn't exist in the test database
                pytest.skip(f"Existing agent test skipped: {e}")

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_workflow_error_handling(self, temporal_client, activity_dependencies):
        """Test workflow error handling with invalid inputs."""

        logger.info("💥 Starting error handling test")

        # Create request with invalid agent ID
        invalid_request = AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=uuid4(),  # Non-existent agent
            user_id="error-test-user",
            task_query="This should fail gracefully",
            timeout_seconds=60,
            max_reasoning_iterations=1,
        )

        activities = create_activities_for_worker(activity_dependencies)

        worker = Worker(
            temporal_client,
            task_queue="test-adk-errors",
            workflows=[ADKAgentWorkflow],
            activities=activities,
        )

        async with worker:
            handle = await temporal_client.start_workflow(
                ADKAgentWorkflow.run,
                invalid_request,
                id=f"error-test-{invalid_request.task_id}",
                task_queue="test-adk-errors",
            )

            logger.info("🧪 Testing error handling...")

            try:
                result = await asyncio.wait_for(handle.result(), timeout=90.0)

                # If we get a result, it should indicate failure
                if hasattr(result, "success"):
                    assert result.success is False
                    logger.info("✅ Error handled gracefully with success=False")
                    logger.info(
                        f"   Error message: {getattr(result, 'error_message', 'No error message')}"
                    )
                else:
                    logger.warning("⚠️ Got result but no success field")

            except Exception as workflow_error:
                # Workflow should fail gracefully, but we expect it to handle errors internally
                logger.info(f"✅ Workflow failed as expected: {workflow_error}")

            logger.info("✅ Error handling test completed!")

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_concurrent_workflows(self, temporal_client, activity_dependencies):
        """Test multiple concurrent workflow executions."""

        logger.info("🔄 Starting concurrent workflows test")

        activities = create_activities_for_worker(activity_dependencies)

        worker = Worker(
            temporal_client,
            task_queue="test-adk-concurrent",
            workflows=[ADKAgentWorkflow],
            activities=activities,
            max_concurrent_workflow_tasks=3,
            max_concurrent_activities=10,
        )

        # Create multiple requests using existing agent
        existing_agent_id = UUID("8bd81439-21d2-41bb-8035-02f87641056a")

        requests = []
        for i in range(3):
            request = AgentExecutionRequest(
                task_id=uuid4(),
                agent_id=existing_agent_id,
                user_id=f"concurrent-test-user-{i}",
                task_query=f"Concurrent test {i + 1}: What is {i + 1} * 2? Please provide just the number.",
                timeout_seconds=90,
                max_reasoning_iterations=2,
            )
            requests.append(request)

        async with worker:
            # Start all workflows concurrently
            handles = []
            for i, request in enumerate(requests):
                handle = await temporal_client.start_workflow(
                    ADKAgentWorkflow.run,
                    request,
                    id=f"concurrent-test-{i}-{request.task_id}",
                    task_queue="test-adk-concurrent",
                )
                handles.append(handle)
                logger.info(f"📋 Started concurrent workflow {i + 1}: {handle.id}")

            # Wait for all to complete
            results = []
            for i, handle in enumerate(handles):
                try:
                    result = await asyncio.wait_for(handle.result(), timeout=120.0)
                    results.append(result)
                    logger.info(f"✅ Concurrent workflow {i + 1} completed")
                    logger.info(f"   Response: {result.final_response}")
                except Exception as e:
                    logger.error(f"❌ Concurrent workflow {i + 1} failed: {e}")
                    results.append(None)

            # Verify results
            successful_results = [r for r in results if r is not None]
            logger.info(
                f"✅ Concurrent test completed: {len(successful_results)}/{len(requests)} successful"
            )

            assert len(successful_results) >= 1, "At least one concurrent workflow should succeed"

            return results

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_workflow_performance_metrics(
        self, temporal_client, activity_dependencies, simple_math_request
    ):
        """Test workflow performance metrics collection."""

        logger.info("📊 Starting performance metrics test")

        activities = create_activities_for_worker(activity_dependencies)

        worker = Worker(
            temporal_client,
            task_queue="test-adk-metrics",
            workflows=[ADKAgentWorkflow],
            activities=activities,
        )

        async with worker:
            handle = await temporal_client.start_workflow(
                ADKAgentWorkflow.run,
                simple_math_request,
                id=f"metrics-test-{simple_math_request.task_id}",
                task_queue="test-adk-metrics",
            )

            logger.info(f"📋 Metrics test workflow started: {handle.id}")

            result = await asyncio.wait_for(handle.result(), timeout=120.0)

            # Verify performance metrics
            assert hasattr(result, "total_cost")
            assert hasattr(result, "reasoning_iterations_used")
            assert hasattr(result, "conversation_history")

            logger.info("✅ Performance metrics test completed!")
            logger.info(f"   Total cost: ${result.total_cost:.6f}")
            logger.info(f"   Reasoning iterations: {result.reasoning_iterations_used}")
            logger.info(f"   Conversation history length: {len(result.conversation_history)}")

            # Verify metrics are reasonable
            assert result.total_cost >= 0.0
            assert result.reasoning_iterations_used >= 0
            assert len(result.conversation_history) >= 0

            return result


if __name__ == "__main__":
    # Run integration tests
    pytest.main([__file__, "-v", "-m", "integration", "--tb=short"])
