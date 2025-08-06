#!/usr/bin/env python3
"""
Test worker for ADK Agent Workflow.

This script creates a dedicated Temporal worker for testing the ADK agent workflow.
It can be run independently to test workflow execution without the full application.
"""

import asyncio
import logging
import signal
import sys
from uuid import uuid4

from temporalio.client import Client
from temporalio.worker import Worker

# Import workflow and dependencies
from agentarea_execution.adk_temporal.workflows.adk_agent_workflow import ADKAgentWorkflow
from agentarea_execution import create_activities_for_worker
from agentarea_execution.models import AgentExecutionRequest
from agentarea_execution.interfaces import ActivityDependencies

# Import dependencies
from agentarea_common.config import get_settings
from agentarea_common.events.router import get_event_router
from agentarea_secrets import get_real_secret_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class ADKTestWorker:
    """Test worker for ADK agent workflows."""

    def __init__(self, task_queue: str = "test-adk-workflow"):
        self.task_queue = task_queue
        self.client = None
        self.worker = None
        self.shutdown_event = asyncio.Event()

    async def create_dependencies(self) -> ActivityDependencies:
        """Create activity dependencies."""
        settings = get_settings()
        event_broker = get_event_router(settings.broker)
        secret_manager = get_real_secret_manager()
        
        return ActivityDependencies(
            settings=settings,
            event_broker=event_broker,
            secret_manager=secret_manager
        )

    async def connect(self) -> None:
        """Connect to Temporal server."""
        try:
            self.client = await Client.connect("localhost:7233")
            logger.info("✅ Connected to Temporal server")
        except Exception as e:
            logger.error(f"❌ Failed to connect to Temporal server: {e}")
            raise

    async def create_worker(self) -> None:
        """Create and configure the test worker."""
        if not self.client:
            raise RuntimeError("Client not connected. Call connect() first.")

        # Create dependencies and activities
        dependencies = await self.create_dependencies()
        activities = create_activities_for_worker(dependencies)

        # Create worker
        self.worker = Worker(
            self.client,
            task_queue=self.task_queue,
            workflows=[ADKAgentWorkflow],
            activities=activities,
            max_concurrent_workflow_tasks=2,
            max_concurrent_activities=10
        )
        
        logger.info(f"✅ Test worker created for task queue: {self.task_queue}")

    async def run_test_workflow(self, request: AgentExecutionRequest) -> None:
        """Run a test workflow."""
        if not self.client:
            raise RuntimeError("Client not connected")

        try:
            # Start workflow
            handle = await self.client.start_workflow(
                ADKAgentWorkflow.run,
                request,
                id=f"test-workflow-{request.task_id}",
                task_queue=self.task_queue
            )
            
            logger.info(f"🚀 Started test workflow: {handle.id}")
            logger.info(f"   Task ID: {request.task_id}")
            logger.info(f"   Agent ID: {request.agent_id}")
            logger.info(f"   Query: {request.task_query}")
            
            # Wait for result
            result = await handle.result()
            
            logger.info("✅ Test workflow completed!")
            logger.info(f"   Success: {result.success}")
            logger.info(f"   Final Response: {result.final_response}")
            logger.info(f"   Total Cost: ${result.total_cost:.6f}")
            logger.info(f"   Conversation History: {len(result.conversation_history)} messages")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Test workflow failed: {e}")
            raise

    async def run_worker(self) -> None:
        """Run the worker until shutdown."""
        if not self.worker:
            raise RuntimeError("Worker not created. Call create_worker() first.")

        logger.info("🏃 Starting test worker...")
        
        # Start worker in background
        worker_task = asyncio.create_task(self.worker.run())
        
        try:
            # Wait for shutdown signal
            await self.shutdown_event.wait()
        except KeyboardInterrupt:
            logger.info("⌨️ Received keyboard interrupt")
        finally:
            logger.info("🛑 Shutting down test worker...")
            worker_task.cancel()
            
            try:
                await worker_task
            except asyncio.CancelledError:
                logger.info("✅ Worker task cancelled successfully")

    def signal_handler(self, signum: int, frame) -> None:
        """Handle shutdown signals."""
        logger.info(f"📡 Received signal {signum}, initiating shutdown...")
        self.shutdown_event.set()

    async def start(self) -> None:
        """Start the test worker."""
        try:
            await self.connect()
            await self.create_worker()
            await self.run_worker()
        except Exception as e:
            logger.error(f"❌ Test worker failed: {e}")
            raise


async def run_single_test():
    """Run a single test workflow execution."""
    logger.info("🧪 Running single test workflow execution")
    
    worker = ADKTestWorker("single-test-queue")
    
    try:
        await worker.connect()
        await worker.create_worker()
        
        # Create test request using existing agent
        from uuid import UUID
        existing_agent_id = UUID("8bd81439-21d2-41bb-8035-02f87641056a")
        
        test_request = AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=existing_agent_id,
            user_id="test-worker-user",
            task_query="Hello! This is a test from the test worker. Please respond with 'Test worker execution successful!' and tell me what you are.",
            timeout_seconds=120,
            max_reasoning_iterations=3
        )
        
        # Run worker in background
        worker_task = asyncio.create_task(worker.worker.run())
        
        # Wait a moment for worker to start
        await asyncio.sleep(2)
        
        # Run test workflow
        result = await worker.run_test_workflow(test_request)
        
        # Cancel worker
        worker_task.cancel()
        
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        
        logger.info("🎉 Single test completed successfully!")
        return result
        
    except Exception as e:
        logger.error(f"❌ Single test failed: {e}")
        raise


async def run_interactive_worker():
    """Run worker in interactive mode for manual testing."""
    logger.info("🎮 Starting interactive test worker")
    logger.info("   Use Temporal UI or CLI to start workflows")
    logger.info("   Task queue: test-adk-interactive")
    logger.info("   Press Ctrl+C to stop")
    
    worker = ADKTestWorker("test-adk-interactive")
    
    # Setup signal handlers
    for sig in [signal.SIGTERM, signal.SIGINT]:
        signal.signal(sig, worker.signal_handler)
    
    await worker.start()


async def run_math_test():
    """Run a simple math test."""
    logger.info("🧮 Running math test workflow")
    
    worker = ADKTestWorker("math-test-queue")
    
    try:
        await worker.connect()
        await worker.create_worker()
        
        # Create math test request using existing agent
        from uuid import UUID
        existing_agent_id = UUID("8bd81439-21d2-41bb-8035-02f87641056a")
        
        math_request = AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=existing_agent_id,
            user_id="math-test-user",
            task_query="What is 15 + 27? Please provide just the number as your answer.",
            timeout_seconds=60,
            max_reasoning_iterations=2
        )
        
        # Run worker in background
        worker_task = asyncio.create_task(worker.worker.run())
        
        # Wait a moment for worker to start
        await asyncio.sleep(2)
        
        # Run test workflow
        result = await worker.run_test_workflow(math_request)
        
        # Verify math result
        if result.success and result.final_response:
            response_text = result.final_response.lower()
            if "42" in response_text:
                logger.info("✅ Math test passed! Correct answer found.")
            else:
                logger.warning(f"⚠️ Math test result unclear: {result.final_response}")
        
        # Cancel worker
        worker_task.cancel()
        
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        
        logger.info("🎉 Math test completed!")
        return result
        
    except Exception as e:
        logger.error(f"❌ Math test failed: {e}")
        raise


async def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python test_adk_workflow_worker.py single    # Run single test")
        print("  python test_adk_workflow_worker.py math      # Run math test")
        print("  python test_adk_workflow_worker.py worker    # Run interactive worker")
        sys.exit(1)
    
    mode = sys.argv[1].lower()
    
    try:
        if mode == "single":
            await run_single_test()
        elif mode == "math":
            await run_math_test()
        elif mode == "worker":
            await run_interactive_worker()
        else:
            logger.error(f"❌ Unknown mode: {mode}")
            sys.exit(1)
            
    except KeyboardInterrupt:
        logger.info("⌨️ Interrupted by user")
    except Exception as e:
        logger.error(f"❌ Test worker error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())