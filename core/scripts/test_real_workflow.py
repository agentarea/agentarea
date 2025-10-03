#!/usr/bin/env python3
"""Test script to run a real workflow execution and monitor for completion issues."""

import asyncio
import logging
import os
import sys
from datetime import timedelta
from uuid import uuid4

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

# Add the core directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentarea_execution.activities.agent_execution_activities import make_agent_activities
from agentarea_execution.models import AgentExecutionRequest
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow


class MockDependencies:
    """Mock dependencies for testing."""

    class MockSecretManager:
        async def get_secret(self, secret_name: str) -> str:
            return f"mock-api-key-{secret_name}"

    class MockEventBroker:
        def __init__(self):
            self.published_events = []

        async def publish(self, event):
            self.published_events.append(event)

    def __init__(self):
        self.secret_manager = self.MockSecretManager()
        self.event_broker = self.MockEventBroker()


async def test_workflow_completion():
    """Test workflow completion with real Temporal setup."""
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # Create mock dependencies
    dependencies = MockDependencies()

    # Create activities
    activities = make_agent_activities(dependencies)

    # Connect to Temporal
    client = await Client.connect("localhost:7233", data_converter=pydantic_data_converter)

    # Create execution request
    execution_request = AgentExecutionRequest(
        agent_id=uuid4(),
        task_id=uuid4(),
        user_id="test-user",
        task_query="Write a simple hello world program in Python",
        task_parameters={
            "success_criteria": ["Program written and explained"],
            "max_iterations": 5,  # Reasonable limit
        },
        budget_usd=0.50,  # Small budget to test budget termination
        requires_human_approval=False,
    )

    workflow_id = f"test-workflow-{uuid4()}"

    logger.info(f"Starting workflow test: {workflow_id}")
    logger.info(f"Task: {execution_request.task_query}")
    logger.info(f"Max iterations: {execution_request.task_parameters['max_iterations']}")
    logger.info(f"Budget: ${execution_request.budget_usd}")

    # Start worker
    async with Worker(
        client,
        task_queue="test-queue",
        workflows=[AgentExecutionWorkflow],
        activities=activities,
    ):
        try:
            # Execute workflow with timeout
            result = await client.execute_workflow(
                AgentExecutionWorkflow.run,
                execution_request,
                id=workflow_id,
                task_queue="test-queue",
                execution_timeout=timedelta(minutes=5),  # 5 minute timeout
            )

            logger.info("✅ Workflow completed successfully!")
            logger.info(f"Success: {result.success}")
            logger.info(f"Iterations used: {result.reasoning_iterations_used}")
            logger.info(f"Total cost: ${result.total_cost:.4f}")
            logger.info(f"Final response: {result.final_response[:200]}...")

            return True

        except Exception as e:
            logger.error(f"❌ Workflow failed: {e}")
            logger.error(f"Error type: {type(e).__name__}")

            # Try to get workflow state for debugging
            try:
                handle = client.get_workflow_handle(workflow_id)
                current_state = await handle.query("get_current_state")
                logger.error(f"Final state: {current_state}")
            except Exception as query_error:
                logger.error(f"Could not query final state: {query_error}")

            return False

    await client.close()


async def main():
    """Main test function."""
    print("🧪 Testing Real Workflow Execution")
    print("=" * 50)

    success = await test_workflow_completion()

    if success:
        print("\n✅ Test completed successfully - workflow finished as expected")
        sys.exit(0)
    else:
        print("\n❌ Test failed - workflow did not complete properly")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
