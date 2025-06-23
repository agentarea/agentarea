#!/usr/bin/env python3
"""Temporal Worker for AgentArea.

This script starts a Temporal worker that can execute our agent task workflows
and activities. It registers all necessary workflows and activities with Temporal.
"""

import asyncio
import logging
import signal
import sys

import dotenv
from temporalio.client import Client
from temporalio.worker import Worker

from agentarea.config import get_settings

# Import our workflow and activity definitions
from agentarea.workflows.agent_task_workflow import (
    AgentTaskWorkflow,
    execute_agent_activity,
    execute_agent_communication_activity,
    execute_custom_tool_activity,
    execute_dynamic_activity,
    execute_mcp_tool_activity,
    validate_agent_activity,
)

dotenv.load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class TemporalWorker:
    """Temporal worker for AgentArea workflows."""

    def __init__(self):
        self.settings = get_settings()
        self.client: Client | None = None
        self.worker: Worker | None = None
        self.should_stop = False

        # Setup signal handlers for graceful shutdown
        signal.signal(
            signal.SIGINT,
            lambda signum, frame: asyncio.create_task(self._signal_handler(signum, frame)),
        )
        signal.signal(
            signal.SIGTERM,
            lambda signum, frame: asyncio.create_task(self._signal_handler(signum, frame)),
        )

    async def _signal_handler(self, signum: int, frame) -> None:
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.should_stop = True
        await self.shutdown()

    async def connect(self) -> None:
        """Connect to Temporal server."""
        temporal_url = self.settings.workflow.TEMPORAL_SERVER_URL
        namespace = self.settings.workflow.TEMPORAL_NAMESPACE

        logger.info(f"Connecting to Temporal server at {temporal_url}, namespace: {namespace}")

        try:
            self.client = await Client.connect(temporal_url, namespace=namespace)
            logger.info("Successfully connected to Temporal server")

        except Exception as e:
            logger.error(f"Failed to connect to Temporal server: {e}")
            raise

    async def create_worker(self) -> None:
        """Create and configure Temporal worker."""
        if not self.client:
            raise RuntimeError("Client not connected. Call connect() first.")

        task_queue = self.settings.workflow.TEMPORAL_TASK_QUEUE
        max_concurrent_activities = self.settings.workflow.TEMPORAL_MAX_CONCURRENT_ACTIVITIES
        max_concurrent_workflows = self.settings.workflow.TEMPORAL_MAX_CONCURRENT_WORKFLOWS

        logger.info(f"Creating worker for task queue: {task_queue}")
        logger.info(f"Max concurrent activities: {max_concurrent_activities}")
        logger.info(f"Max concurrent workflows: {max_concurrent_workflows}")

        # Create worker with our workflows and activities
        self.worker = Worker(
            self.client,
            task_queue=task_queue,
            workflows=[AgentTaskWorkflow],
            activities=[
                validate_agent_activity,
                execute_agent_activity,
                execute_dynamic_activity,
                execute_mcp_tool_activity,
                execute_custom_tool_activity,
                execute_agent_communication_activity,
            ],
            max_concurrent_activities=max_concurrent_activities,
            max_concurrent_workflow_tasks=max_concurrent_workflows,
        )

        logger.info("Worker created successfully")

    async def run(self) -> None:
        """Run the worker (blocking)."""
        if not self.worker:
            raise RuntimeError("Worker not created. Call create_worker() first.")

        logger.info("Starting Temporal worker...")
        logger.info("Worker is ready to process workflows and activities")

        try:
            # Run worker until shutdown signal
            await self.worker.run()

        except asyncio.CancelledError:
            logger.info("Worker was cancelled")
        except Exception as e:
            logger.error(f"Worker error: {e}")
            raise
        finally:
            logger.info("Worker stopped")

    async def start(self) -> None:
        """Start the worker (full initialization and run)."""
        try:
            await self.connect()
            await self.create_worker()
            await self.run()

        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        except Exception as e:
            logger.error(f"Worker startup failed: {e}")
            raise
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        logger.info("Shutting down worker...")

        if self.worker:
            try:
                # Cancel worker tasks
                await self.worker.shutdown()
                logger.info("Worker shutdown initiated")
            except Exception as e:
                logger.error(f"Error during worker shutdown: {e}")

        if self.client:
            try:
                # Close client connection
                await self.client.close()
                logger.info("Client connection closed")
            except Exception as e:
                logger.error(f"Error closing client: {e}")


async def start_worker() -> None:
    """Main entry point for starting the Temporal worker."""
    logger.info("🚀 Starting AgentArea Temporal Worker")

    # Validate settings
    settings = get_settings()

    # Log configuration
    logger.info(f"Temporal Server: {settings.workflow.TEMPORAL_SERVER_URL}")
    logger.info(f"Namespace: {settings.workflow.TEMPORAL_NAMESPACE}")
    logger.info(f"Task Queue: {settings.workflow.TEMPORAL_TASK_QUEUE}")
    logger.info(
        f"Max Concurrent Activities: {settings.workflow.TEMPORAL_MAX_CONCURRENT_ACTIVITIES}"
    )
    logger.info(f"Max Concurrent Workflows: {settings.workflow.TEMPORAL_MAX_CONCURRENT_WORKFLOWS}")

    # Start worker
    worker = TemporalWorker()

    try:
        await worker.start()
    except Exception as e:
        logger.error(f"Worker failed: {e}")
        sys.exit(1)

    logger.info("✅ AgentArea Temporal Worker stopped")


if __name__ == "__main__":
    """Run worker when script is executed directly."""
    try:
        asyncio.run(start_worker())
    except KeyboardInterrupt:
        logger.info("Worker interrupted by user")
    except Exception as e:
        logger.error(f"Worker failed: {e}")
        sys.exit(1)
