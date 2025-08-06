"""Integration test for AgentExecutionWorkflow with real Temporal worker."""

import asyncio
import logging
import sys
import uuid
from datetime import timedelta

# Add core to path for imports
sys.path.insert(0, "core")

from agentarea_common.config import get_settings
from agentarea_execution import create_activities_for_worker, ActivityDependencies
from agentarea_execution.models import AgentExecutionRequest
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_secrets import get_real_secret_manager
from agentarea_common.events.router import get_event_router
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.common import RetryPolicy

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class IntegrationTestRunner:
    """Runs integration tests with real Temporal worker."""

    def __init__(self):
        self.client = None
        self.worker = None
        self.worker_task = None

    async def setup(self):
        """Set up Temporal client and worker for testing."""
        settings = get_settings()
        
        # Connect to Temporal
        self.client = await Client.connect(
            settings.workflow.TEMPORAL_SERVER_URL,
            namespace=settings.workflow.TEMPORAL_NAMESPACE,
        )
        logger.info("Connected to Temporal server")

        # Create test dependencies
        dependencies = ActivityDependencies(
            settings=settings,
            event_broker=get_event_router(settings.broker),
            secret_manager=get_real_secret_manager()
        )

        # Create activities
        activities = create_activities_for_worker(dependencies)

        # Create worker with test task queue
        test_task_queue = f"test-queue-{uuid.uuid4().hex[:8]}"
        self.worker = Worker(
            self.client,
            task_queue=test_task_queue,
            workflows=[AgentExecutionWorkflow],
            activities=activities,
            max_concurrent_workflow_tasks=1,
            max_concurrent_activities=2,
        )
        
        # Start worker in background
        self.worker_task = asyncio.create_task(self.worker.run())
        logger.info(f"Test worker started on queue: {test_task_queue}")
        
        # Give worker time to start
        await asyncio.sleep(1)
        
        return test_task_queue

    async def teardown(self):
        """Clean up test resources."""
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
            logger.info("Test worker stopped")

        if self.client:
            # Client cleanup is automatic
            self.client = None

    async def test_simple_agent_execution(self, task_queue: str):
        """Test a simple agent execution workflow."""
        logger.info("=== Testing Simple Agent Execution ===")

        # Create a test agent execution request
        request = AgentExecutionRequest(
            agent_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            user_id="test-user",
            task_query="Say hello and complete the task",
            task_parameters={
                "success_criteria": ["Provide a greeting", "Signal completion"],
                "max_iterations": 3
            },
            budget_usd=1.0,
            requires_human_approval=False
        )

        try:
            # Start workflow
            workflow_id = f"test-workflow-{uuid.uuid4().hex[:8]}"
            handle = await self.client.start_workflow(
                AgentExecutionWorkflow.run,
                request,
                id=workflow_id,
                task_queue=task_queue,
                execution_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=1)
            )
            
            logger.info(f"Started workflow: {workflow_id}")

            # Wait for result
            result = await handle.result()
            
            logger.info(f"Workflow completed successfully!")
            logger.info(f"Success: {result.success}")
            logger.info(f"Final response: {result.final_response}")
            logger.info(f"Iterations used: {result.reasoning_iterations_used}")
            logger.info(f"Total cost: ${result.total_cost:.6f}")
            
            return result.success

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            return False

    async def test_workflow_with_tools(self, task_queue: str):
        """Test agent execution with tool usage."""
        logger.info("\n=== Testing Agent Execution with Tools ===")

        # Create a request that should use tools
        request = AgentExecutionRequest(
            agent_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            user_id="test-user",
            task_query="Use available tools to complete a simple task and then signal completion",
            task_parameters={
                "success_criteria": [
                    "Use at least one available tool",
                    "Complete the task successfully"
                ],
                "max_iterations": 5
            },
            budget_usd=2.0,
            requires_human_approval=False
        )

        try:
            # Start workflow
            workflow_id = f"test-tools-workflow-{uuid.uuid4().hex[:8]}"
            handle = await self.client.start_workflow(
                AgentExecutionWorkflow.run,
                request,
                id=workflow_id,
                task_queue=task_queue,
                execution_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=1)
            )
            
            logger.info(f"Started tools workflow: {workflow_id}")

            # Wait for result
            result = await handle.result()
            
            logger.info(f"Tools workflow completed!")
            logger.info(f"Success: {result.success}")
            logger.info(f"Final response: {result.final_response}")
            logger.info(f"Iterations used: {result.reasoning_iterations_used}")
            logger.info(f"Total cost: ${result.total_cost:.6f}")
            
            return result.success

        except Exception as e:
            logger.error(f"Tools workflow execution failed: {e}")
            return False

    async def test_workflow_max_iterations(self, task_queue: str):
        """Test workflow termination at max iterations."""
        logger.info("\n=== Testing Max Iterations Termination ===")

        # Create a request with very low max iterations
        request = AgentExecutionRequest(
            agent_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            user_id="test-user",
            task_query="Complete an impossible task that will never finish",
            task_parameters={
                "success_criteria": ["Achieve the impossible"],
                "max_iterations": 2  # Very low limit
            },
            budget_usd=0.5,
            requires_human_approval=False
        )

        try:
            # Start workflow
            workflow_id = f"test-max-iter-{uuid.uuid4().hex[:8]}"
            handle = await self.client.start_workflow(
                AgentExecutionWorkflow.run,
                request,
                id=workflow_id,
                task_queue=task_queue,
                execution_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=1)
            )
            
            logger.info(f"Started max iterations workflow: {workflow_id}")

            # Wait for result
            result = await handle.result()
            
            logger.info(f"Max iterations workflow completed!")
            logger.info(f"Success: {result.success}")
            logger.info(f"Iterations used: {result.reasoning_iterations_used}")
            logger.info(f"Should have hit max iterations: {result.reasoning_iterations_used == 2}")
            
            # Should not succeed but should complete properly
            return not result.success and result.reasoning_iterations_used == 2

        except Exception as e:
            logger.error(f"Max iterations workflow failed: {e}")
            return False


async def main():
    """Run integration tests."""
    logger.info("Starting AgentExecutionWorkflow integration tests...")
    
    runner = IntegrationTestRunner()
    
    try:
        # Setup test environment
        task_queue = await runner.setup()
        
        # Run tests
        tests = [
            ("Simple agent execution", runner.test_simple_agent_execution),
            ("Agent execution with tools", runner.test_workflow_with_tools),
            ("Max iterations termination", runner.test_workflow_max_iterations),
        ]
        
        results = []
        for test_name, test_func in tests:
            try:
                success = await test_func(task_queue)
                results.append((test_name, success))
                logger.info(f"✓ {test_name}: {'PASSED' if success else 'FAILED'}")
            except Exception as e:
                logger.error(f"✗ {test_name}: ERROR - {e}")
                results.append((test_name, False))
        
        # Summary
        passed = sum(1 for _, success in results if success)
        total = len(results)
        
        logger.info(f"\n=== Integration Test Summary ===")
        for test_name, success in results:
            status = "✓ PASSED" if success else "✗ FAILED"
            logger.info(f"{status}: {test_name}")
        
        logger.info(f"\nPassed: {passed}/{total} tests")
        
        if passed == total:
            logger.info("🎉 All integration tests passed!")
            return True
        else:
            logger.warning(f"⚠ {total - passed} tests failed")
            return False
            
    except Exception as e:
        logger.error(f"Integration test setup failed: {e}")
        return False
    finally:
        await runner.teardown()


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)