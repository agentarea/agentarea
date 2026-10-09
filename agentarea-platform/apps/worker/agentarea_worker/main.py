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
from agentarea_common.config import (
    RedisSettings,
    Settings,
    get_app_settings,
    get_settings,
    temporal_connect_config,
)
from agentarea_common.events.factory import create_event_broker
from agentarea_common.logging import setup_logging
from agentarea_common.observability import get_temporal_plugins, setup_otel
from agentarea_common.workflow.sandbox import create_workflow_runner
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

from agentarea_worker.health import HealthServer, WorkerHealth, WorkerHealthSettings

# Load environment variables
dotenv.load_dotenv()

# Configure structured (JSON) logging. Routing every record through
# WorkspaceContextFormatter escapes newlines, so untrusted values in log
# messages can't forge log lines (see LogSanitizerFilter for the plain-text path).
setup_logging(
    level="DEBUG" if get_app_settings().DEBUG else "INFO",
    enable_structured_logging=True,
)
logger = logging.getLogger(__name__)


def _redis_url(settings: Settings) -> str:
    """The Redis URL the channel machinery needs, or a loud failure.

    ``settings.broker`` is RedisSettings or KafkaSettings depending on
    AGENTAREA_BROKER, and only the former carries a URL. Defaulting to
    localhost here would let a misconfigured worker start and then fail
    connecting, which is how it reported "Connect call failed" against
    localhost while compose had handed it redis://valkey:6379.
    """
    if not isinstance(settings.broker, RedisSettings):
        raise RuntimeError(
            "Channel delivery requires the Redis broker; set AGENTAREA_BROKER=redis "
            f"(current: {settings.broker.BROKER})"
        )
    return settings.broker.REDIS_URL


def create_activity_dependencies() -> ActivityDependencies:
    """Create basic dependencies needed by activities.

    Activities will create their own database sessions and services
    using these basic dependencies for better retryability.
    """
    # Get settings for configuration
    settings = get_settings()

    # Get event broker
    event_broker = create_event_broker(settings.broker)

    # Create secret manager factory with settings
    from agentarea_secrets import SecretManagerFactory

    secret_manager_factory = SecretManagerFactory(settings.secret_manager)

    # Shared BrokerClient for outbound channel delivery. Built here (not
    # inside _setup_channel_subscribers) so the publish_workflow_events
    # activity can enqueue deliveries directly without going through the
    # lossy pub/sub bridge.
    from agentarea_common.broker import RedisStreamsBroker

    broker_client = RedisStreamsBroker(_redis_url(settings))

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
        self.inbound_autoclaimer = None
        self.delivery_consumer = None
        self.delivery_autoclaimer = None
        self.outbox_relay = None
        self.stream_runtime = None
        self._broker = None
        self._dedup = None
        self._inbound_dedup = None
        self.container_monitor = None
        self.dispatch_stamps = None
        self.worker_shutdown_event = asyncio.Event()
        self.health = WorkerHealth()
        # All interfaces: the kubelet probes the pod IP, not loopback.
        self.health_server = HealthServer(
            self.health,
            host="0.0.0.0",  # noqa: S104
            port=WorkerHealthSettings().HEALTH_PORT,
        )

    async def signal_handler(self, signum: int, frame: Any) -> None:
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.worker_shutdown_event.set()

    async def connect(self) -> None:
        """Connect to Temporal server."""
        settings = get_settings()
        setup_otel("agentarea-worker", settings.observability)
        self.client = await Client.connect(
            **temporal_connect_config(),
            data_converter=pydantic_data_converter,
            plugins=get_temporal_plugins(settings.observability),
        )
        logger.info("Connected to Temporal server")

    async def create_worker(self) -> None:
        """Create and configure the Temporal worker."""
        if not self.client:
            raise RuntimeError("Client not connected. Call connect() first.")

        settings = get_settings()

        await self._check_database()

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
        initialize_di_container(settings.temporal)

        # Discover extensions and wire permission service
        from agentarea_common.auth.authorization import AuthorizationService
        from agentarea_common.auth.permission import PermissionService
        from agentarea_common.auth.workspace_authorization import (
            WorkspaceScopedAuthorizationService,
        )
        from agentarea_common.config.app import get_app_settings
        from agentarea_common.di.container import register_factory, register_singleton
        from agentarea_common.extensions import discover_extensions
        from agentarea_common.extensions.registry import ExtensionRegistry
        from agentarea_common.features.service import DeploymentMode, FeatureService

        discover_extensions()

        # Resolve now, after discovery, and let a failure stop startup. An installed
        # pricing extension that cannot be resolved leaves the currency unknown, and
        # a process running anyway would record amounts in a different currency from
        # its siblings; exiting lets the orchestrator restart it instead.
        from agentarea_common.extensions.customer_pricing import get_customer_pricing

        logger.info("Billing currency: %s", get_customer_pricing().currency())

        app_settings = get_app_settings()
        mode = DeploymentMode(app_settings.EDITION)
        register_singleton(FeatureService, FeatureService(mode=mode))

        openfga_client = None
        if settings.access_control.BACKEND == "openfga":
            from agentarea_common.rebac.openfga_bootstrap import bootstrap_openfga
            from agentarea_common.rebac.openfga_client import OpenFGAClient

            if not settings.openfga.API_TOKEN:
                logger.warning(
                    "AGENTAREA_AUTHZ_FGA_API_TOKEN is not set: OpenFGA calls are "
                    "unauthenticated. Set AGENTAREA_AUTHZ_FGA_API_TOKEN and the "
                    "server's OPENFGA_AUTHN_PRESHARED_KEYS to require a bearer token."
                )
            await bootstrap_openfga(settings.openfga)
            openfga_client = OpenFGAClient(
                api_url=settings.openfga.URL,
                store_id=settings.openfga.STORE_ID,
                authorization_model_id=settings.openfga.MODEL_ID,
                timeout_seconds=settings.openfga.TIMEOUT.total_seconds(),
                api_token=settings.openfga.API_TOKEN or None,
            )
            register_singleton(OpenFGAClient, openfga_client)

        # PermissionService is a SELECTOR extension point: exactly one impl is
        # active, and an EXPLICIT AGENTAREA_AUTHZ_BACKEND must win over a merely
        # installed "permissions" extension. (Previously the extension was checked
        # first and silently overrode the configured backend, so OpenFGA never
        # enforced.) The extension is a FALLBACK, used only when the operator did
        # not select a concrete backend. See AGENTS.md "Extension points".
        backend = settings.access_control.BACKEND
        perm_factory = ExtensionRegistry.get_factory("permissions")
        if openfga_client is not None:
            from agentarea_common.auth.openfga_permission import OpenFGAPermissionService

            register_singleton(PermissionService, OpenFGAPermissionService(openfga_client))
            perm_impl = "OpenFGAPermissionService"
        elif perm_factory:
            register_factory(PermissionService, perm_factory)
            perm_impl = "extension:permissions"
        else:
            raise RuntimeError(
                "No PermissionService is available: AGENTAREA_AUTHZ_BACKEND="
                f"{backend!r} selects no graph backend and no 'permissions' extension "
                "is installed. Refusing to start rather than falling back to an "
                "implementation that allows every check -- an authorization backend "
                "that is merely absent must not read as permission granted. Set "
                "AGENTAREA_AUTHZ_BACKEND=openfga and point it at a running instance."
            )

        if perm_factory and perm_impl != "extension:permissions":
            logger.warning(
                "Ignoring registered 'permissions' extension: AGENTAREA_AUTHZ_BACKEND=%s "
                "selects %s explicitly. An extension cannot override an explicit backend.",
                backend,
                perm_impl,
            )
        logger.info("PermissionService=%s (AGENTAREA_AUTHZ_BACKEND=%s)", perm_impl, backend)

        authz_factory = ExtensionRegistry.get_factory("authorization")
        if authz_factory:
            register_factory(AuthorizationService, authz_factory)
        else:
            register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())

        # Create governance interceptor pipeline
        from agentarea_governance.bridges.temporal_bridge import (
            GovernanceWorkerInterceptor,
            validate_activity_mapping,
        )
        from agentarea_governance.factory import create_governance_pipeline

        governance_pipeline = create_governance_pipeline()
        all_activities = activities + mcp_activities
        validate_activity_mapping(all_activities)

        self.worker = Worker(
            self.client,
            task_queue=settings.temporal.QUEUE,
            workflows=[
                AgentExecutionWorkflow,
            ],
            activities=activities + mcp_activities,
            interceptors=[GovernanceWorkerInterceptor(governance_pipeline)],
            workflow_runner=create_workflow_runner(),
            max_concurrent_workflow_tasks=settings.temporal.MAX_WORKFLOWS,
            max_concurrent_activities=settings.temporal.MAX_ACTIVITIES,
            max_cached_workflows=settings.temporal.MAX_CACHED,
            graceful_shutdown_timeout=settings.temporal.SHUTDOWN_GRACE,
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
            workflow_runner=create_workflow_runner(),
            max_concurrent_workflow_tasks=5,
            max_concurrent_activities=5,
        )

        # Wire inbound channel message consumer (event-service → Redis Streams → Python)
        # Wire outbound channel event subscriber (workflow events → Telegram/Slack/Discord)
        await self._setup_channel_subscribers(dependencies)

        from agentarea_worker.streams import build_stream_runtime

        self.stream_runtime = build_stream_runtime(settings, dependencies)

        logger.info("Worker created and configured")

    async def _check_database(self) -> None:
        from agentarea_common.config.database import get_database
        from sqlalchemy import text

        async with get_database().engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        logger.info("Database reachable")

    async def _setup_channel_subscribers(self, dependencies) -> None:
        """Wire inbound stream consumer + outbound delivery consumer.

        The router-via-pub/sub bridge is gone: `publish_workflow_events_activity`
        now enqueues channel deliveries directly via `dependencies.broker_client`.
        This method only wires the *consumer side* (delivery loop +
        autoclaimer) and the inbound channel event consumer.
        """
        from agentarea_common.broker import DedupCache
        from agentarea_common.config.database import get_database
        from agentarea_triggers.channels import get_adapter
        from agentarea_triggers.channels.adapters import register_all_adapters
        from agentarea_triggers.channels.autoclaimer import StreamAutoclaimer
        from agentarea_triggers.channels.delivery_consumer import (
            ChannelDeliveryConsumer,
        )
        from agentarea_triggers.channels.inbound_subscriber import InboundMessageStreamConsumer
        from agentarea_triggers.channels.lazy_secret_manager import LazySecretReader
        from agentarea_triggers.channels.origin_guard import TriggerWorkspaceGuard

        settings = get_settings()
        redis_url = _redis_url(settings)
        delivery_cfg = settings.channel_delivery

        # Broker comes from dependencies — same instance the activity uses
        # for producer-side submits. Shutdown closes it once.
        if dependencies.broker_client is None:
            raise RuntimeError("broker_client missing from deps")
        self._broker = dependencies.broker_client
        self._dedup = DedupCache(
            redis_url,
            prefix="channel-delivery",
            ttl_seconds=int(delivery_cfg.DEDUP_TTL.total_seconds()),
        )
        self._inbound_dedup = DedupCache(
            redis_url,
            prefix="channel-inbound",
            ttl_seconds=int(delivery_cfg.DEDUP_TTL.total_seconds()),
        )

        # Inbound: event-service webhook/polling → Redis Streams → Python task execution
        self.inbound_subscriber = InboundMessageStreamConsumer(
            broker=self._broker,
            dedup=self._inbound_dedup,
            event_broker=dependencies.event_broker,
            secret_manager_factory=dependencies.secret_manager_factory,
            workflow_executor=dependencies.workflow_executor,
            stream=delivery_cfg.IN_STREAM,
            group=delivery_cfg.IN_GROUP,
            dlq_stream=delivery_cfg.IN_DLQ,
            block_ms=int(delivery_cfg.BLOCK.total_seconds() * 1000),
            batch_size=delivery_cfg.BATCH_SIZE,
            max_delivery_attempts=delivery_cfg.MAX_ATTEMPTS,
        )
        self.inbound_autoclaimer = StreamAutoclaimer(
            broker=self._broker,
            stream=delivery_cfg.IN_STREAM,
            group=delivery_cfg.IN_GROUP,
            consumer_id="inbound-autoclaimer",
            min_idle_ms=int(delivery_cfg.AUTOCLAIM_IDLE.total_seconds() * 1000),
            interval_seconds=delivery_cfg.AUTOCLAIM_EVERY.total_seconds(),
        )

        # Register adapters; they raise typed Retryable/Fatal errors that the
        # delivery consumer translates into ACK / requeue / DLQ.
        secret_reader = LazySecretReader(dependencies.secret_manager_factory)
        # redis_url enables the Telegram streaming (edit-in-place) sender.
        register_all_adapters(secret_reader, redis_url)

        self.delivery_consumer = ChannelDeliveryConsumer(
            broker=self._broker,
            dedup=self._dedup,
            adapter_resolver=get_adapter,
            origin_guard=TriggerWorkspaceGuard(get_database().async_session_factory),
            stream=delivery_cfg.OUT_STREAM,
            group=delivery_cfg.OUT_GROUP,
            dlq_stream=delivery_cfg.OUT_DLQ,
            block_ms=int(delivery_cfg.BLOCK.total_seconds() * 1000),
            batch_size=delivery_cfg.BATCH_SIZE,
            max_delivery_attempts=delivery_cfg.MAX_ATTEMPTS,
        )
        self.delivery_autoclaimer = StreamAutoclaimer(
            broker=self._broker,
            stream=delivery_cfg.OUT_STREAM,
            group=delivery_cfg.OUT_GROUP,
            consumer_id="autoclaimer",
            min_idle_ms=int(delivery_cfg.AUTOCLAIM_IDLE.total_seconds() * 1000),
            interval_seconds=delivery_cfg.AUTOCLAIM_EVERY.total_seconds(),
        )

        # Transactional outbox relay: drains event_outbox rows (written in the
        # same txn as the aggregate change by domain services) and publishes them
        # to the event broker, or performs the ones that have a handler. FOR
        # UPDATE SKIP LOCKED lets it co-reside with any number of workers
        # without coordination.
        from agentarea_common.config.database import get_database
        from agentarea_common.events.outbox_relay import OutboxRelay
        from agentarea_common.workspaces import (
            MEMBERSHIP_ENDED,
            get_workspace_membership_graph,
            membership_removal_handler,
        )

        self.outbox_relay = OutboxRelay(
            session_factory=get_database().async_session_factory,
            event_broker=dependencies.event_broker,
            handlers={
                MEMBERSHIP_ENDED: membership_removal_handler(get_workspace_membership_graph()),
            },
        )

    async def run(self) -> None:
        """Run the worker until shutdown signal."""
        if not self.worker:
            raise RuntimeError("Worker not created. Call create_worker() first.")

        logger.info("Worker starting...")

        # Start channel subscribers and delivery pipeline
        if self.inbound_subscriber:
            await self.inbound_subscriber.start()
        if self.inbound_autoclaimer:
            await self.inbound_autoclaimer.start()
        if self.delivery_consumer:
            await self.delivery_consumer.start()
        if self.delivery_autoclaimer:
            await self.delivery_autoclaimer.start()
        if self.outbox_relay:
            await self.outbox_relay.start()
        if self.stream_runtime:
            await self.stream_runtime.start()

        # Start MCP container monitor in background
        from agentarea_mcp.container_monitor import start_container_monitoring

        self.container_monitor = await start_container_monitoring()

        from agentarea_common.config.database import get_database
        from agentarea_mcp.dispatch_stamps import DispatchStampWriter

        self.dispatch_stamps = DispatchStampWriter(get_database().async_session_factory)
        await self.dispatch_stamps.start()

        # Start workers in background
        pollers = {w.task_queue: w for w in (self.worker, self.trigger_worker) if w}
        worker_tasks = {queue: asyncio.create_task(w.run()) for queue, w in pollers.items()}
        self.health.mark_started(pollers)

        # Wait for a shutdown signal, or for a Temporal worker to stop on its own:
        # a worker that stopped polling must take the process down with it, not
        # leave a pod that looks alive and does nothing.
        shutdown = asyncio.create_task(self.worker_shutdown_event.wait())
        await asyncio.wait([shutdown, *worker_tasks.values()], return_when=asyncio.FIRST_COMPLETED)
        stopped = [queue for queue, task in worker_tasks.items() if task.done()]
        if stopped:
            logger.error("Temporal worker stopped unexpectedly on %s", ", ".join(stopped))
        else:
            logger.info("Shutdown signal received, stopping worker...")

        shutdown.cancel()
        # shutdown() stops polling and lets in-flight activities finish within the
        # graceful timeout; cancelling run() would cut them off at once.
        await asyncio.gather(
            *(worker.shutdown() for queue, worker in pollers.items() if queue not in stopped)
        )
        failure: Exception | None = None
        for queue, task in worker_tasks.items():
            try:
                await task
            except asyncio.CancelledError:
                # Expected during worker shutdown - task cancellation is normal
                pass
            except Exception as e:
                logger.error("Temporal worker on %s failed", queue, exc_info=True)
                failure = failure or e
        logger.info("Workers stopped")

        if stopped:
            raise RuntimeError(
                f"Temporal worker on {', '.join(stopped)} stopped polling"
            ) from failure

    async def start(self) -> None:
        """Start the worker with proper initialization."""
        try:
            await self.health_server.start()
            await self.connect()
            await self.create_worker()
            await self.run()
        except Exception as e:
            logger.exception(f"Worker failed to start: {e}")
            raise
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Shutdown the worker and cleanup resources."""
        logger.info("Shutting down worker...")

        if self.dispatch_stamps:
            await self.dispatch_stamps.stop()
            self.dispatch_stamps = None
        if self.container_monitor:
            await self.container_monitor.stop()
            self.container_monitor = None
        if self.stream_runtime:
            await self.stream_runtime.stop()
            self.stream_runtime = None
        if self.outbox_relay:
            await self.outbox_relay.stop()
            self.outbox_relay = None
        if self.inbound_subscriber:
            await self.inbound_subscriber.stop()
            self.inbound_subscriber = None
        if self.inbound_autoclaimer:
            await self.inbound_autoclaimer.stop()
            self.inbound_autoclaimer = None
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
        if self._inbound_dedup:
            await self._inbound_dedup.aclose()
            self._inbound_dedup = None

        if self.worker:
            self.worker = None
        if self.trigger_worker:
            self.trigger_worker = None

        if self.client:
            # Temporal client doesn't have explicit close method
            self.client = None

        await self.health_server.stop()

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
        logger.exception(f"Worker error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
