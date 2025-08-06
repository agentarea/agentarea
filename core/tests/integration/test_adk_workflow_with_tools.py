#!/usr/bin/env python3
"""
Test ADK workflow with tools to verify separate LLM and tool call activities.

This test ensures that the Temporal interceptors properly create separate activities
for LLM calls and tool calls, rather than bundling everything into one activity.
"""

import asyncio
import logging
from uuid import uuid4, UUID

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


class ADKWorkflowWithToolsTest:
    """Test ADK workflow with tools to verify separate activities."""

    def __init__(self, task_queue: str = "test-adk-tools"):
        self.task_queue = task_queue
        self.client = None
        self.worker = None

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
            max_concurrent_workflow_tasks=1,
            max_concurrent_activities=10
        )
        
        logger.info(f"✅ Test worker created for task queue: {self.task_queue}")

    async def test_complex_agent_with_tools(self) -> None:
        """Test agent that should use both LLM calls and tool calls."""
        if not self.client:
            raise RuntimeError("Client not connected")

        # Use existing agent with tools
        existing_agent_id = UUID("8bd81439-21d2-41bb-8035-02f87641056a")
        
        # Create a request that should trigger tool usage
        test_request = AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=existing_agent_id,
            user_id="tools-test-user",
            task_query="Hello! Please use the test_function tool to greet me with the name 'Alice'. Also, can you calculate what 15 * 3 equals using the calculator tool?",
            timeout_seconds=180,
            max_reasoning_iterations=5
        )

        try:
            # Start workflow
            handle = await self.client.start_workflow(
                ADKAgentWorkflow.run,
                test_request,
                id=f"tools-test-{test_request.task_id}",
                task_queue=self.task_queue
            )
            
            logger.info(f"🚀 Started tools test workflow: {handle.id}")
            logger.info(f"   Task ID: {test_request.task_id}")
            logger.info(f"   Agent ID: {test_request.agent_id}")
            logger.info(f"   Query: {test_request.task_query}")
            
            # Wait for result
            result = await handle.result()
            
            logger.info("✅ Tools test workflow completed!")
            logger.info(f"   Success: {result.success}")
            logger.info(f"   Final Response: {result.final_response}")
            logger.info(f"   Total Cost: ${result.total_cost:.6f}")
            logger.info(f"   Conversation History: {len(result.conversation_history)} messages")
            logger.info(f"   Reasoning Iterations: {result.reasoning_iterations_used}")
            
            # Check if the response contains evidence of tool usage
            if result.final_response:
                response_lower = result.final_response.lower()
                if "alice" in response_lower and ("45" in result.final_response or "forty" in response_lower):
                    logger.info("🎉 SUCCESS: Agent appears to have used both tools correctly!")
                else:
                    logger.warning("⚠️ Agent response doesn't show clear evidence of tool usage")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Tools test workflow failed: {e}")
            raise

    async def test_simple_llm_only(self) -> None:
        """Test simple LLM-only request to compare activity patterns."""
        if not self.client:
            raise RuntimeError("Client not connected")

        # Use existing agent
        existing_agent_id = UUID("8bd81439-21d2-41bb-8035-02f87641056a")
        
        # Create a simple request that shouldn't need tools
        test_request = AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=existing_agent_id,
            user_id="simple-test-user",
            task_query="Just say hello and tell me what you are. Don't use any tools.",
            timeout_seconds=120,
            max_reasoning_iterations=2
        )

        try:
            # Start workflow
            handle = await self.client.start_workflow(
                ADKAgentWorkflow.run,
                test_request,
                id=f"simple-test-{test_request.task_id}",
                task_queue=self.task_queue
            )
            
            logger.info(f"🚀 Started simple test workflow: {handle.id}")
            
            # Wait for result
            result = await handle.result()
            
            logger.info("✅ Simple test workflow completed!")
            logger.info(f"   Success: {result.success}")
            logger.info(f"   Final Response: {result.final_response}")
            logger.info(f"   Reasoning Iterations: {result.reasoning_iterations_used}")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Simple test workflow failed: {e}")
            raise

    async def run_tests(self) -> None:
        """Run all tests."""
        try:
            await self.connect()
            await self.create_worker()
            
            # Run worker in background
            worker_task = asyncio.create_task(self.worker.run())
            
            # Wait a moment for worker to start
            await asyncio.sleep(2)
            
            logger.info("🧪 Running simple LLM-only test first...")
            await self.test_simple_llm_only()
            
            logger.info("\n" + "="*60)
            logger.info("🧪 Running complex agent with tools test...")
            await self.test_complex_agent_with_tools()
            
            # Cancel worker
            worker_task.cancel()
            
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
            
            logger.info("🎉 All tests completed successfully!")
            
        except Exception as e:
            logger.error(f"❌ Test failed: {e}")
            raise


async def main():
    """Main entry point."""
    test = ADKWorkflowWithToolsTest()
    
    try:
        await test.run_tests()
    except KeyboardInterrupt:
        logger.info("⌨️ Interrupted by user")
    except Exception as e:
        logger.error(f"❌ Test error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())