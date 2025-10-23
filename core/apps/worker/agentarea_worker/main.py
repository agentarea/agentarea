#!/usr/bin/env python3
"""AgentArea Temporal Worker Application.

This is the main Temporal worker that executes agent task workflows
and activities. It registers all necessary workflows and activities with Temporal.
"""

import asyncio
import logging
import signal
import sys
from typing import Any

import dotenv

# Initialize DI container with proper config injection
from agentarea_agents.infrastructure.di_container import initialize_di_container
from agentarea_common.config import get_settings
from agentarea_common.events.router import get_event_router
from agentarea_execution import create_activities_for_worker
from agentarea_execution.interfaces import ActivityDependencies

# Import workflow and activity definitions from the execution library
from agentarea_execution.workflows.agent_execution_workflow import (
    AgentExecutionWorkflow,
)
from agentarea_secrets import get_real_secret_manager
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

# Load environment variables
dotenv.load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

import os  # noqa: E402

import litellm  # noqa: E402

os.environ["OLLAMA_API_BASE"] = "http://host.docker.internal:11434"
print(litellm.supports_function_calling("ollama_chat/qwen2.5"))


def create_activity_dependencies() -> ActivityDependencies:
    """Create basic dependencies needed by activities.

    Activities will create their own database sessions and services
    using these basic dependencies for better retryability.
    """
    # Get settings for configuration
    settings = get_settings()

    # Get event broker
    event_broker = get_event_router(settings.broker)

    # Create secret manager factory with settings
    from agentarea_secrets import SecretManagerFactory

    secret_manager_factory = SecretManagerFactory(settings.secret_manager)

    # Create dependency container
    return ActivityDependencies(
        settings=settings,
        event_broker=event_broker,
        secret_manager_factory=secret_manager_factory,
    )


class AgentAreaWorker:
    """Temporal worker for AgentArea workflows and activities."""

    def __init__(self):
        self.client = None
        self.worker = None
        self.worker_shutdown_event = asyncio.Event()

    async def signal_handler(self, signum: int, frame: Any) -> None:
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.worker_shutdown_event.set()

    async def connect(self) -> None:
        """Connect to Temporal server."""
        settings = get_settings()
        self.client = await Client.connect(
            settings.workflow.TEMPORAL_SERVER_URL,
            namespace=settings.workflow.TEMPORAL_NAMESPACE,
            data_converter=pydantic_data_converter,
        )
        logger.info("Connected to Temporal server")

    async def create_worker(self) -> None:
        """Create and configure the Temporal worker."""
        if not self.client:
            raise RuntimeError("Client not connected. Call connect() first.")

        settings = get_settings()

        # Create basic dependencies for activities
        dependencies = create_activity_dependencies()
        activities = create_activities_for_worker(dependencies)

        # Initialize DI container for workflows
        initialize_di_container(settings.workflow)

        self.worker = Worker(
            self.client,
            task_queue=settings.workflow.TEMPORAL_TASK_QUEUE,
            workflows=[AgentExecutionWorkflow],
            activities=activities,
            max_concurrent_workflow_tasks=settings.workflow.TEMPORAL_MAX_CONCURRENT_WORKFLOWS,
            max_concurrent_activities=settings.workflow.TEMPORAL_MAX_CONCURRENT_ACTIVITIES,
        )
        logger.info("Worker created and configured")

    async def run(self) -> None:
        """Run the worker until shutdown signal."""
        if not self.worker:
            raise RuntimeError("Worker not created. Call create_worker() first.")

        logger.info("Worker starting...")

        # Start worker in background
        worker_task = asyncio.create_task(self.worker.run())

        # Wait for shutdown signal
        await self.worker_shutdown_event.wait()

        logger.info("Shutdown signal received, stopping worker...")
        worker_task.cancel()

        try:
            await worker_task
        except asyncio.CancelledError:
            logger.info("Worker task cancelled successfully")

    async def start(self) -> None:
        """Start the worker with proper initialization."""
        try:
            await self.connect()
            await self.create_worker()
            await self.run()
        except Exception as e:
            logger.error(f"Worker failed to start: {e}")
            raise
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Shutdown the worker and cleanup resources."""
        logger.info("Shutting down worker...")

        if self.worker:
            # Worker cleanup is handled in run() method
            self.worker = None

        if self.client:
            # Temporal client doesn't have explicit close method
            self.client = None

        logger.info("Worker shutdown complete")


async def main() -> None:
    """Main entry point for the worker application."""
    worker = AgentAreaWorker()

    # Setup signal handlers
    for sig in [signal.SIGTERM, signal.SIGINT]:
        signal.signal(sig, lambda s, f: asyncio.create_task(worker.signal_handler(s, f)))

    try:
        await worker.start()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Worker error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
