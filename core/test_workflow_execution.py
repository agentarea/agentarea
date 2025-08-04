#!/usr/bin/env python3
"""
Test script for AgentExecutionWorkflow without ADK dependencies.

Run from core/ directory with: python test_workflow_execution.py
"""

import asyncio
import logging
import uuid
from datetime import timedelta
from typing import Any

from temporalio.client import Client
from temporalio.worker import Worker

# Import our workflow and activities
from libs.execution.agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from libs.execution.agentarea_execution.activities.agent_execution_activities import make_agent_activities
from libs.execution.agentarea_execution.interfaces import ActivityDependencies
from libs.execution.agentarea_execution.models import AgentExecutionRequest

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Mock dependencies for testing
class MockEventBroker:
    async def publish(self, event: Any) -> None:
        logger.info("Mock event published: %s", str(event)[:100])

class MockSecretManager:
    async def get_secret(self, key: str) -> str:
        return f"mock_secret_for_{key}"

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

def create_test_dependencies() -> ActivityDependencies:
    """Create mock dependencies for testing."""
    return ActivityDependencies(
        settings=MockSettings(),  # type: ignore
        event_broker=MockEventBroker(),  # type: ignore
        secret_manager=MockSecretManager()  # type: ignore
    )

async def run_worker_and_test():
    """Run both worker and test in the same process."""
    
    # Create test dependencies
    dependencies = create_test_dependencies()
    
    # Create activities
    activities = make_agent_activities(dependencies)
    logger.info(f"Created {len(activities)} activities for testing")
    
    # Connect to Temporal
    client = await Client.connect("localhost:7233")
    logger.info("Connected to Temporal server")
    
    # Create worker
    worker = Worker(
        client,
        task_queue="agent-execution-test",
        workflows=[AgentExecutionWorkflow],
        activities=activities,
        max_concurrent_workflow_tasks=1,
        max_concurrent_activities=5,
    )
    
    logger.info("Created worker, starting in background...")
    
    # Start worker in background
    worker_task = asyncio.create_task(worker.run())
    
    # Give worker time to start
    await asyncio.sleep(2)
    
    try:
        # Now test the workflow
        await test_workflow(client)
        
    finally:
        # Stop worker
        logger.info("Stopping worker...")
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            logger.info("Worker stopped")

async def test_workflow(client: Client):
    """Test the workflow execution."""
    
    # Create test request with real agent ID
    test_request = AgentExecutionRequest(
        task_id=uuid.uuid4(),
        agent_id=uuid.UUID("8bd81439-21d2-41bb-8035-02f87641056a"),  # Real agent from database
        user_id="dev-user",
        task_query="Test task: Generate a simple hello world message",
        task_parameters={
            "success_criteria": ["Message should contain 'Hello World'"],
            "max_iterations": 2
        },
        timeout_seconds=120,
        max_reasoning_iterations=2,
        budget_usd=1.0
    )
    
    logger.info(f"Starting workflow execution for task: {test_request.task_id}")
    
    # Start workflow
    handle = await client.start_workflow(
        AgentExecutionWorkflow.run,
        test_request,
        id=f"test-workflow-{test_request.task_id}",
        task_queue="agent-execution-test",
        execution_timeout=timedelta(minutes=5),
    )
    
    logger.info(f"Workflow started with ID: {handle.id}")
    
    # Wait for result
    try:
        result = await handle.result()
        logger.info("=== WORKFLOW COMPLETED SUCCESSFULLY ===")
        logger.info(f"Success: {result.success}")
        logger.info(f"Final response: {result.final_response}")
        logger.info(f"Iterations used: {result.reasoning_iterations_used}")
        logger.info(f"Total cost: ${result.total_cost:.6f}")
        logger.info(f"Messages count: {len(result.conversation_history)}")
        
        if result.conversation_history:
            logger.info("=== CONVERSATION HISTORY ===")
            for i, msg in enumerate(result.conversation_history):
                logger.info(f"Message {i+1}: {msg.get('role', 'unknown')} - {str(msg.get('content', ''))[:100]}...")
        
        return result
        
    except Exception as e:
        logger.error(f"Workflow failed: {e}")
        # Try to get workflow history for debugging
        try:
            async for event in handle.fetch_history():
                logger.error(f"History event: {event}")
        except Exception as hist_e:
            logger.error(f"Could not fetch history: {hist_e}")
        raise

async def main():
    """Main entry point."""
    logger.info("Starting AgentExecutionWorkflow test...")
    
    try:
        await run_worker_and_test()
        logger.info("=== TEST COMPLETED SUCCESSFULLY ===")
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == "__main__":
    asyncio.run(main())