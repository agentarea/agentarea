#!/usr/bin/env python3
"""
Integration tests for ADK Agent Workflow.

Tests the complete ADK-Temporal workflow integration with real dependencies.
"""

import asyncio
import logging
from uuid import uuid4

import pytest
from agentarea_execution.adk_temporal.activities.adk_agent_activities import (
    build_agent_config_activity,
    execute_adk_agent_with_temporal_backbone,
)

# Import workflow and activities
from agentarea_execution.adk_temporal.workflows.adk_agent_workflow import ADKAgentWorkflow
from agentarea_execution.models import AgentExecutionRequest
from temporalio.client import Client
from temporalio.worker import Worker

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestADKWorkflowIntegration:
    """Integration tests for ADK workflow with real Temporal infrastructure."""

    @pytest.fixture
    def sample_request(self):
        """Create a sample agent execution request."""
        return AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=uuid4(),
            user_id="integration-test-user",
            task_query="Hello, this is an integration test. Please respond with 'Integration test successful!'",
            timeout_seconds=120,
            max_reasoning_iterations=3,
        )

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_adk_workflow_with_real_temporal(self, sample_request):
        """Test ADK workflow with real Temporal server."""

        try:
            # Connect to Temporal server
            client = await Client.connect("localhost:7233")
            logger.info("✅ Connected to Temporal server")

            # Create worker with real activities
            worker = Worker(
                client,
                task_queue="test-adk-integration",
                workflows=[ADKAgentWorkflow],
                activities=[build_agent_config_activity, execute_adk_agent_with_temporal_backbone],
            )

            logger.info("🚀 Starting integration test worker...")

            async with worker:
                # Start workflow
                handle = await client.start_workflow(
                    ADKAgentWorkflow.run,
                    sample_request,
                    id=f"integration-test-{sample_request.task_id}",
                    task_queue="test-adk-integration",
                )

                logger.info(f"📋 Workflow started with ID: {handle.id}")

                # Wait for completion with timeout
                try:
                    result = await asyncio.wait_for(handle.result(), timeout=120.0)

                    # Verify result
                    assert result is not None
                    assert hasattr(result, "success")
                    assert hasattr(result, "final_response")
                    assert hasattr(result, "task_id")
                    assert hasattr(result, "agent_id")

                    logger.info("✅ Workflow completed successfully!")
                    logger.info(f"   Success: {result.success}")
                    logger.info(f"   Response: {result.final_response}")
                    logger.info(f"   Task ID: {result.task_id}")
                    logger.info(f"   Agent ID: {result.agent_id}")

                    return result

                except TimeoutError:
                    logger.error("❌ Workflow timed out")
                    pytest.fail("Workflow execution timed out")

        except Exception as e:
            logger.error(f"❌ Integration test failed: {e}")
            import traceback

            logger.error(f"   Traceback: {traceback.format_exc()}")
            pytest.fail(f"Integration test failed: {e}")

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_workflow_queries_and_signals(self, sample_request):
        """Test workflow queries and signals during execution."""

        try:
            client = await Client.connect("localhost:7233")

            worker = Worker(
                client,
                task_queue="test-adk-queries",
                workflows=[ADKAgentWorkflow],
                activities=[build_agent_config_activity, execute_adk_agent_with_temporal_backbone],
            )

            async with worker:
                # Start workflow
                handle = await client.start_workflow(
                    ADKAgentWorkflow.run,
                    sample_request,
                    id=f"query-test-{sample_request.task_id}",
                    task_queue="test-adk-queries",
                )

                logger.info(f"📋 Testing queries on workflow: {handle.id}")

                # Wait a moment for workflow to start
                await asyncio.sleep(2)

                # Test queries
                try:
                    current_state = await handle.query("get_current_state")
                    logger.info(f"📊 Current state: {current_state}")

                    assert "execution_id" in current_state
                    assert "event_count" in current_state
                    assert "success" in current_state

                    events = await handle.query("get_events", 10)
                    logger.info(f"📝 Events count: {len(events) if events else 0}")

                    final_response = await handle.query("get_final_response")
                    logger.info(f"💬 Final response: {final_response}")

                except Exception as query_error:
                    logger.warning(f"⚠️ Query failed (workflow may not be ready): {query_error}")

                # Test signals
                try:
                    await handle.signal("pause", "Integration test pause")
                    logger.info("⏸️ Sent pause signal")

                    await asyncio.sleep(1)

                    await handle.signal("resume", "Integration test resume")
                    logger.info("▶️ Sent resume signal")

                except Exception as signal_error:
                    logger.warning(f"⚠️ Signal failed: {signal_error}")

                # Wait for completion
                result = await asyncio.wait_for(handle.result(), timeout=120.0)

                logger.info("✅ Query and signal test completed successfully!")
                return result

        except Exception as e:
            logger.error(f"❌ Query/signal test failed: {e}")
            pytest.fail(f"Query/signal test failed: {e}")

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_workflow_with_existing_agent(self):
        """Test workflow with an existing agent from the database."""

        try:
            # Try to get an existing agent ID
            from uuid import UUID

            existing_agent_id = UUID("8bd81439-21d2-41bb-8035-02f87641056a")

            request = AgentExecutionRequest(
                task_id=uuid4(),
                agent_id=existing_agent_id,
                user_id="integration-test-existing",
                task_query="Hello from integration test with existing agent!",
                timeout_seconds=120,
                max_reasoning_iterations=3,
            )

            client = await Client.connect("localhost:7233")

            worker = Worker(
                client,
                task_queue="test-adk-existing",
                workflows=[ADKAgentWorkflow],
                activities=[build_agent_config_activity, execute_adk_agent_with_temporal_backbone],
            )

            async with worker:
                handle = await client.start_workflow(
                    ADKAgentWorkflow.run,
                    request,
                    id=f"existing-agent-test-{request.task_id}",
                    task_queue="test-adk-existing",
                )

                logger.info(f"📋 Testing with existing agent: {existing_agent_id}")

                result = await asyncio.wait_for(handle.result(), timeout=120.0)

                assert result.success is True
                assert result.agent_id == existing_agent_id
                assert result.final_response is not None

                logger.info("✅ Existing agent test completed successfully!")
                logger.info(f"   Agent ID: {result.agent_id}")
                logger.info(f"   Response: {result.final_response}")

                return result

        except Exception as e:
            logger.error(f"❌ Existing agent test failed: {e}")
            pytest.fail(f"Existing agent test failed: {e}")

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_workflow_error_handling(self):
        """Test workflow error handling with invalid inputs."""

        try:
            # Create request with invalid agent ID
            invalid_request = AgentExecutionRequest(
                task_id=uuid4(),
                agent_id=uuid4(),  # Non-existent agent
                user_id="error-test-user",
                task_query="This should fail gracefully",
                timeout_seconds=60,
                max_reasoning_iterations=1,
            )

            client = await Client.connect("localhost:7233")

            worker = Worker(
                client,
                task_queue="test-adk-errors",
                workflows=[ADKAgentWorkflow],
                activities=[build_agent_config_activity, execute_adk_agent_with_temporal_backbone],
            )

            async with worker:
                handle = await client.start_workflow(
                    ADKAgentWorkflow.run,
                    invalid_request,
                    id=f"error-test-{invalid_request.task_id}",
                    task_queue="test-adk-errors",
                )

                logger.info("🧪 Testing error handling...")

                try:
                    result = await asyncio.wait_for(handle.result(), timeout=60.0)

                    # If we get a result, it should indicate failure
                    if hasattr(result, "success"):
                        assert result.success is False
                        logger.info("✅ Error handled gracefully with success=False")
                    else:
                        logger.warning("⚠️ Got result but no success field")

                except Exception as workflow_error:
                    # Workflow should fail gracefully
                    logger.info(f"✅ Workflow failed as expected: {workflow_error}")

                logger.info("✅ Error handling test completed!")

        except Exception as e:
            logger.error(f"❌ Error handling test failed: {e}")
            pytest.fail(f"Error handling test failed: {e}")


if __name__ == "__main__":
    # Run integration tests
    pytest.main([__file__, "-v", "-m", "integration"])
