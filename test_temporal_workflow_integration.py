"""Integration test for Temporal workflow with real activities."""

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


class TemporalWorkflowTester:
    """Tests Temporal workflow integration with real activities."""

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
        await asyncio.sleep(2)
        
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

    async def test_completion_detection(self, task_queue: str):
        """Test that workflow properly detects task completion."""
        logger.info("=== Testing Completion Detection ===")

        # Create a test agent execution request
        request = AgentExecutionRequest(
            agent_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            user_id="test-user",
            task_query="Complete this simple test task",
            task_parameters={
                "success_criteria": ["Task completed successfully"],
                "max_iterations": 5
            },
            budget_usd=1.0,
            requires_human_approval=False
        )

        try:
            # Start workflow
            workflow_id = f"test-completion-{uuid.uuid4().hex[:8]}"
            handle = await self.client.start_workflow(
                AgentExecutionWorkflow.run,
                request,
                id=workflow_id,
                task_queue=task_queue,
                execution_timeout=timedelta(minutes=3),
                retry_policy=RetryPolicy(maximum_attempts=1)
            )
            
            logger.info(f"Started workflow: {workflow_id}")

            # Wait for result
            result = await handle.result()
            
            logger.info(f"Workflow completed!")
            logger.info(f"Success: {result.success}")
            logger.info(f"Final response: {result.final_response}")
            logger.info(f"Iterations used: {result.reasoning_iterations_used}")
            logger.info(f"Total cost: ${result.total_cost:.6f}")
            
            # Verify completion detection worked
            if result.success:
                logger.info("✅ Completion detection working correctly!")
                return True
            else:
                logger.warning("⚠ Workflow completed but success=False")
                return False

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            return False

    async def test_tool_call_processing(self, task_queue: str):
        """Test that tool calls are processed correctly."""
        logger.info("\n=== Testing Tool Call Processing ===")

        # Create a request that should trigger tool usage
        request = AgentExecutionRequest(
            agent_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            user_id="test-user",
            task_query="Use the task_complete tool to finish this task",
            task_parameters={
                "success_criteria": [
                    "Use the task_complete tool",
                    "Provide a completion message"
                ],
                "max_iterations": 3
            },
            budget_usd=1.0,
            requires_human_approval=False
        )

        try:
            # Start workflow
            workflow_id = f"test-tools-{uuid.uuid4().hex[:8]}"
            handle = await self.client.start_workflow(
                AgentExecutionWorkflow.run,
                request,
                id=workflow_id,
                task_queue=task_queue,
                execution_timeout=timedelta(minutes=3),
                retry_policy=RetryPolicy(maximum_attempts=1)
            )
            
            logger.info(f"Started tools workflow: {workflow_id}")

            # Wait for result
            result = await handle.result()
            
            logger.info(f"Tools workflow completed!")
            logger.info(f"Success: {result.success}")
            logger.info(f"Final response: {result.final_response}")
            logger.info(f"Iterations used: {result.reasoning_iterations_used}")
            
            # Check conversation history for tool usage
            tool_messages = [msg for msg in result.conversation_history if hasattr(msg, 'role') and msg.role == 'tool']
            logger.info(f"Tool messages found: {len(tool_messages)}")
            
            if result.success and len(tool_messages) > 0:
                logger.info("✅ Tool call processing working correctly!")
                return True
            else:
                logger.warning("⚠ Tool calls may not be processed correctly")
                return False

        except Exception as e:
            logger.error(f"Tools workflow execution failed: {e}")
            return False

    async def test_max_iterations_limit(self, task_queue: str):
        """Test that max iterations limit is respected."""
        logger.info("\n=== Testing Max Iterations Limit ===")

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
                execution_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=1)
            )
            
            logger.info(f"Started max iterations workflow: {workflow_id}")

            # Wait for result
            result = await handle.result()
            
            logger.info(f"Max iterations workflow completed!")
            logger.info(f"Success: {result.success}")
            logger.info(f"Iterations used: {result.reasoning_iterations_used}")
            
            # Should not succeed but should complete properly
            if not result.success and result.reasoning_iterations_used <= 2:
                logger.info("✅ Max iterations limit working correctly!")
                return True
            else:
                logger.warning(f"⚠ Max iterations behavior unexpected: success={result.success}, iterations={result.reasoning_iterations_used}")
                return False

        except Exception as e:
            logger.error(f"Max iterations workflow failed: {e}")
            return False


async def main():
    """Run Temporal workflow integration tests."""
    logger.info("Starting Temporal workflow integration tests...")
    
    tester = TemporalWorkflowTester()
    
    try:
        # Setup test environment
        task_queue = await tester.setup()
        
        # Run tests
        tests = [
            ("Completion detection", tester.test_completion_detection),
            ("Tool call processing", tester.test_tool_call_processing),
            ("Max iterations limit", tester.test_max_iterations_limit),
        ]
        
        results = []
        for test_name, test_func in tests:
            try:
                success = await test_func(task_queue)
                results.append((test_name, success))
                logger.info(f"{'✓' if success else '✗'} {test_name}: {'PASSED' if success else 'FAILED'}")
            except Exception as e:
                logger.error(f"✗ {test_name}: ERROR - {e}")
                results.append((test_name, False))
        
        # Summary
        passed = sum(1 for _, success in results if success)
        total = len(results)
        
        logger.info(f"\n=== Temporal Integration Test Summary ===")
        for test_name, success in results:
            status = "✓ PASSED" if success else "✗ FAILED"
            logger.info(f"{status}: {test_name}")
        
        logger.info(f"\nPassed: {passed}/{total} tests")
        
        if passed == total:
            logger.info("🎉 All Temporal integration tests passed!")
            return True
        else:
            logger.warning(f"⚠ {total - passed} tests failed")
            return False
            
    except Exception as e:
        logger.error(f"Integration test setup failed: {e}")
        return False
    finally:
        await tester.teardown()


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)