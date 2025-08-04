#!/usr/bin/env python3
"""
Standalone test for AgentExecutionWorkflow without ADK dependencies.

This script runs a Temporal worker and tests the non-ADK workflow functionality.
"""

import asyncio
import logging
import uuid
from datetime import timedelta

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Mock dependencies and services for testing
class MockEventBroker:
    async def publish(self, event) -> None:
        logger.info("Mock event published: %s", event)

class MockSecretManager:
    async def get_secret(self, key: str) -> str:
        return "mock_secret_value"

class MockSettings:
    def __init__(self):
        self.workflow = MockWorkflowSettings()
        self.broker = MockBrokerSettings()

class MockWorkflowSettings:
    TEMPORAL_SERVER_URL = "localhost:7233"
    TEMPORAL_NAMESPACE = "default"
    TEMPORAL_TASK_QUEUE = "agent-execution-test"
    TEMPORAL_MAX_CONCURRENT_WORKFLOWS = 1
    TEMPORAL_MAX_CONCURRENT_ACTIVITIES = 5

class MockBrokerSettings:
    pass

# Create mock dependencies
def create_mock_dependencies():
    import sys
    sys.path.insert(0, '/Users/jamakase/Projects/startup/agentarea')
    
    from core.libs.execution.agentarea_execution.interfaces import ActivityDependencies
    
    return ActivityDependencies(
        settings=MockSettings(),
        event_broker=MockEventBroker(),
        secret_manager=MockSecretManager()
    )

async def run_temporal_worker():
    """Run a minimal Temporal worker for testing."""
    from temporalio.client import Client
    from temporalio.worker import Worker
    from core.libs.execution.agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
    from core.libs.execution.agentarea_execution.activities.agent_execution_activities import make_agent_activities
    
    # Create mock dependencies
    dependencies = create_mock_dependencies()
    
    # Create activities
    activities = make_agent_activities(dependencies)
    logger.info(f"Created {len(activities)} activities for testing")
    
    # Connect to Temporal
    client = await Client.connect("localhost:7233")
    logger.info("Connected to Temporal server")
    
    # Create worker with test queue
    worker = Worker(
        client,
        task_queue="agent-execution-test",
        workflows=[AgentExecutionWorkflow],
        activities=activities,
        max_concurrent_workflow_tasks=1,
        max_concurrent_activities=5,
    )
    
    logger.info("Starting Temporal worker...")
    
    # Run worker (this will block)
    await worker.run()

async def test_workflow_execution():
    """Test the workflow execution."""
    from temporalio.client import Client
    from core.libs.execution.agentarea_execution.models import AgentExecutionRequest
    from core.libs.execution.agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
    
    # Connect to Temporal
    client = await Client.connect("localhost:7233")
    
    # Create test request
    test_request = AgentExecutionRequest(
        task_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        user_id="test-user",
        task_query="Test task: Write a simple hello world message",
        task_parameters={
            "success_criteria": ["Message should contain 'Hello World'"],
            "max_iterations": 3
        },
        timeout_seconds=300,
        max_reasoning_iterations=3,
        budget_usd=1.0
    )
    
    logger.info(f"Starting workflow execution for task: {test_request.task_id}")
    
    # Start workflow
    handle = await client.start_workflow(
        AgentExecutionWorkflow.run,
        test_request,
        id=f"test-workflow-{test_request.task_id}",
        task_queue="agent-execution-test",
        execution_timeout=timedelta(minutes=10),
    )
    
    logger.info(f"Workflow started with ID: {handle.id}")
    
    # Wait for result
    try:
        result = await handle.result()
        logger.info(f"Workflow completed successfully!")
        logger.info(f"Success: {result.success}")
        logger.info(f"Final response: {result.final_response}")
        logger.info(f"Iterations used: {result.reasoning_iterations_used}")
        logger.info(f"Total cost: ${result.total_cost:.6f}")
        return result
    except Exception as e:
        logger.error(f"Workflow failed: {e}")
        raise

async def main():
    """Main test runner."""
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        # Run worker mode
        logger.info("Running in worker mode...")
        await run_temporal_worker()
    else:
        # Run test mode
        logger.info("Running workflow test...")
        await asyncio.sleep(2)  # Give worker time to start
        await test_workflow_execution()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise