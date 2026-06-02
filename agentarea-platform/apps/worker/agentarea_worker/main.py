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
from agentarea_common.events.router import create_event_broker_from_router, get_event_router
from agentarea_execution import create_activities_for_worker
from agentarea_execution.interfaces import ActivityDependencies

# Import workflow and activity definitions from the execution library
from agentarea_execution.workflows.agent_execution_workflow import (
    AgentExecutionWorkflow,
)
from agentarea_mcp.activities import make_mcp_activities
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


def create_activity_dependencies() -> ActivityDependencies:
    """Create basic dependencies needed by activities.

    Activities will create their own database sessions and services
    using these basic dependencies for better retryability.
    """
    # Get settings for configuration
    settings = get_settings()

    # Get event broker
    event_router = get_event_router(settings.broker)
    event_broker = create_event_broker_from_router(event_router)

    # Create secret manager factory with settings
    from agentarea_secrets import SecretManagerFactory

    secret_manager_factory = SecretManagerFactory(settings.secret_manager)

    # Shared BrokerClient for outbound channel delivery. Built here (not
    # inside _setup_channel_subscribers) so the publish_workflow_events
    # activity can enqueue deliveries directly without going through the
    # lossy pub/sub bridge.
    from agentarea_common.broker import RedisStreamsBroker

    redis_url = getattr(settings.broker, "REDIS_URL", "redis://localhost:6379")
    broker_client = RedisStreamsBroker(redis_url)

    return ActivityDependencies(
        settings=settings,
        event_broker=event_broker,
        secret_manager_factory=secret_manager_factory,
        broker_client=broker_client,
        channel_delivery_settings=settings.channel_delivery,
    )


class AgentAreaWorker:
    """Temporal worker for AgentArea workflows and activities."""

    def __init__(self):
        self.client = None
        self.worker = None
        self.trigger_worker = None
        self.inbound_subscriber = None
        self.delivery_consumer = None
        self.delivery_autoclaimer = None
        self._broker = None
        self._dedup = None
        self.container_monitor = None
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

        # Wire the Temporal client into a shared workflow executor so trigger
        # activities can start AgentExecutionWorkflow without creating a second
        # Temporal connection.
        from agentarea_common.workflow.temporal_executor import TemporalWorkflowExecutor

        workflow_executor = TemporalWorkflowExecutor(client=self.client)
        dependencies.workflow_executor = workflow_executor

        activities = create_activities_for_worker(dependencies)
        mcp_activities = make_mcp_activities(dependencies)

        # Initialize DI container for workflows
        initialize_di_container(settings.workflow)

        # Discover extensions and wire permission service
        from agentarea_common.auth.authorization import AuthorizationService
        from agentarea_common.auth.permission import PermissionService
        from agentarea_common.auth.simple_authorization import SimpleAuthorizationService
        from agentarea_common.auth.simple_permission import SimplePermissionService
        from agentarea_common.config.app import get_app_settings
        from agentarea_common.di.container import register_factory, register_singleton
        from agentarea_common.extensions import discover_extensions
        from agentarea_common.extensions.registry import ExtensionRegistry
        from agentarea_common.features.service import DeploymentMode, FeatureService

        discover_extensions()

        app_settings = get_app_settings()
        mode = DeploymentMode(app_settings.DEPLOYMENT_MODE)
        register_singleton(FeatureService, FeatureService(mode=mode))

        perm_factory = ExtensionRegistry.get_factory("permissions")
        if perm_factory:
            register_factory(PermissionService, perm_factory)
        else:
            register_singleton(PermissionService, SimplePermissionService())

        authz_factory = ExtensionRegistry.get_factory("authorization")
        if authz_factory:
            register_factory(AuthorizationService, authz_factory)
        else:
            register_singleton(AuthorizationService, SimpleAuthorizationService())

        # Create governance interceptor pipeline
        from agentarea_governance.bridges.temporal_bridge import (
            GovernanceWorkerInterceptor,
            validate_activity_mapping,
        )
        from agentarea_governance.factory import create_governance_pipeline

        governance_pipeline = create_governance_pipeline()
        all_activities = activities + mcp_activities
        validate_activity_mapping(
            [a.fn.__name__ if hasattr(a, "fn") else str(a) for a in all_activities]
        )

        self.worker = Worker(
            self.client,
            task_queue=settings.workflow.TEMPORAL_TASK_QUEUE,
            workflows=[
                AgentExecutionWorkflow,
            ],
            activities=activities + mcp_activities,
            interceptors=[GovernanceWorkerInterceptor(governance_pipeline)],
            max_concurrent_workflow_tasks=settings.workflow.TEMPORAL_MAX_CONCURRENT_WORKFLOWS,
            max_concurrent_activities=settings.workflow.TEMPORAL_MAX_CONCURRENT_ACTIVITIES,
        )

        # Create trigger execution worker on the trigger-schedules queue
        from agentarea_execution.activities.trigger_execution_activities import (
            make_trigger_activities,
        )
        from agentarea_execution.workflows.trigger_execution_workflow import (
            TriggerExecutionWorkflow,
        )

        trigger_activities = make_trigger_activities(dependencies)
        trigger_queue = getattr(settings, "triggers", None)
        trigger_task_queue = getattr(
            trigger_queue, "TEMPORAL_SCHEDULE_TASK_QUEUE", "trigger-schedules"
        )

        self.trigger_worker = Worker(
            self.client,
            task_queue=trigger_task_queue,
            workflows=[TriggerExecutionWorkflow],
            activities=trigger_activities,
            max_concurrent_workflow_tasks=5,
            max_concurrent_activities=5,
        )

        # Wire inbound channel message subscriber (Go → Redis → Python)
        # Wire outbound channel event subscriber (workflow events → Telegram/Slack/Discord)
        await self._setup_channel_subscribers(dependencies)

        logger.info("Worker created and configured")

    async def _setup_channel_subscribers(self, dependencies) -> None:
        """Wire inbound subscriber + outbound delivery consumer.

        The router-via-pub/sub bridge is gone: `publish_workflow_events_activity`
        now enqueues channel deliveries directly via `dependencies.broker_client`.
        This method only wires the *consumer side* (delivery loop +
        autoclaimer) and the inbound polling subscriber.
        """
        from agentarea_common.broker import DedupCache
        from agentarea_triggers.channels import get_adapter
        from agentarea_triggers.channels.adapters import register_all_adapters
        from agentarea_triggers.channels.autoclaimer import StreamAutoclaimer
        from agentarea_triggers.channels.delivery_consumer import (
            ChannelDeliveryConsumer,
        )
        from agentarea_triggers.channels.inbound_subscriber import InboundMessageSubscriber
        from agentarea_triggers.channels.lazy_secret_manager import LazySecretReader

        settings = get_settings()
        redis_url = getattr(settings.broker, "REDIS_URL", "redis://localhost:6379")
        delivery_cfg = settings.channel_delivery

        # Broker comes from dependencies — same instance the activity uses
        # for producer-side submits. Shutdown closes it once.
        if dependencies.broker_client is None:
            raise RuntimeError("broker_client missing from deps")
        self._broker = dependencies.broker_client
        self._dedup = DedupCache(
            redis_url,
            prefix="channel-delivery",
            ttl_seconds=delivery_cfg.DEDUP_TTL_SECONDS,
        )

        # Inbound: Go polling → Redis → Python task execution
        self.inbound_subscriber = InboundMessageSubscriber(
            redis_url=redis_url,
            event_broker=dependencies.event_broker,
            workflow_executor=dependencies.workflow_executor,
        )

        # Register adapters; they raise typed Retryable/Fatal errors that the
        # delivery consumer translates into ACK / requeue / DLQ.
        secret_reader = LazySecretReader(dependencies.secret_manager_factory)
        register_all_adapters(secret_reader)

        self.delivery_consumer = ChannelDeliveryConsumer(
            broker=self._broker,
            dedup=self._dedup,
            adapter_resolver=get_adapter,
            stream=delivery_cfg.OUTBOUND_STREAM,
            group=delivery_cfg.OUTBOUND_GROUP,
            dlq_stream=delivery_cfg.OUTBOUND_DLQ,
            block_ms=delivery_cfg.CONSUMER_BLOCK_MS,
            batch_size=delivery_cfg.CONSUMER_BATCH_SIZE,
            max_delivery_attempts=delivery_cfg.MAX_DELIVERY_ATTEMPTS,
        )
        self.delivery_autoclaimer = StreamAutoclaimer(
            broker=self._broker,
            stream=delivery_cfg.OUTBOUND_STREAM,
            group=delivery_cfg.OUTBOUND_GROUP,
            consumer_id="autoclaimer",
            min_idle_ms=delivery_cfg.AUTOCLAIM_MIN_IDLE_MS,
            interval_seconds=delivery_cfg.AUTOCLAIM_INTERVAL_SECONDS,
        )

    async def run(self) -> None:
        """Run the worker until shutdown signal."""
        if not self.worker:
            raise RuntimeError("Worker not created. Call create_worker() first.")

        logger.info("Worker starting...")

        # Start channel subscribers and delivery pipeline
        if self.inbound_subscriber:
            await self.inbound_subscriber.start()
        if self.delivery_consumer:
            await self.delivery_consumer.start()
        if self.delivery_autoclaimer:
            await self.delivery_autoclaimer.start()

        # Start MCP container monitor in background
        from agentarea_mcp.container_monitor import start_container_monitoring

        self.container_monitor = await start_container_monitoring()

        # Start workers in background
        worker_task = asyncio.create_task(self.worker.run())
        trigger_task = (
            asyncio.create_task(self.trigger_worker.run()) if self.trigger_worker else None
        )

        # Wait for shutdown signal
        await self.worker_shutdown_event.wait()

        logger.info("Shutdown signal received, stopping worker...")
        worker_task.cancel()
        if trigger_task:
            trigger_task.cancel()

        for task in [worker_task, trigger_task]:
            if task:
                try:
                    await task
                except asyncio.CancelledError:
                    # Expected during worker shutdown - task cancellation is normal
                    pass
        logger.info("Workers stopped")

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

        if self.container_monitor:
            await self.container_monitor.stop()
            self.container_monitor = None
        if self.inbound_subscriber:
            await self.inbound_subscriber.stop()
            self.inbound_subscriber = None
        if self.delivery_autoclaimer:
            await self.delivery_autoclaimer.stop()
            self.delivery_autoclaimer = None
        if self.delivery_consumer:
            await self.delivery_consumer.stop()
            self.delivery_consumer = None
        if self._broker:
            await self._broker.aclose()
            self._broker = None
        if self._dedup:
            await self._dedup.aclose()
            self._dedup = None

        if self.worker:
            self.worker = None
        if self.trigger_worker:
            self.trigger_worker = None

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
