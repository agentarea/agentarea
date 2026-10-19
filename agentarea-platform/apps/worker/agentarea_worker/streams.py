"""Event stream runtime inside the worker: polled-item ingest, partitions, the router, the events view.

The ``ingest`` group on ``streams.ingest`` turns the items the Go event-service
polled into stream events (ADR-0040 §3). The router and the events view are
consumer groups over every partition of ``streams.events`` (ADR-0043 §3, §4):
the ``router`` reacts to each event, the ``events-view`` writes it into the
read model. Both announce what they wrote to the events pages open on the
workspace. The ``platform`` group on ``tasks.events`` writes task outcomes into
each workspace's platform stream (ADR-0040 §5). The router's subscription cache
follows the change notices the outbox relay publishes to ``domain.events``.
"""

import os
import socket
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from agentarea_common.auth.permission import PermissionService
from agentarea_common.broker import DedupCache
from agentarea_common.broker.topics import (
    BUS_RETENTION,
    DELIVERY_GROUP,
    EVENTS_VIEW_GROUP,
    PLATFORM_GROUP,
    ROUTER_GROUP,
    STREAM_EVENTS,
    TASK_EVENTS,
    dead_letter_topic,
    stream_events_partitions,
)
from agentarea_common.config import RedisSettings, Settings
from agentarea_common.config.database import get_database
from agentarea_common.di.container import resolve
from agentarea_common.events.ports import Subscription
from agentarea_common.workspaces import get_workspace_membership_graph
from agentarea_streams.application.events_view import EventsView
from agentarea_streams.application.external_delivery import (
    ExternalDelivery,
    ExternalSubscriptionHandler,
    delivery_topics,
)
from agentarea_streams.application.forward import ForwardHandler
from agentarea_streams.application.platform_projection import PlatformProjection
from agentarea_streams.application.poll_intake import PolledItemConsumer
from agentarea_streams.application.processor import ProcessorHandler
from agentarea_streams.application.router import EventRouter
from agentarea_streams.application.source_intake import ingest_source_event
from agentarea_streams.application.stream_access import StreamReaders
from agentarea_streams.application.webhook_endpoint import WebhookEndpoint
from agentarea_streams.domain import SubscriptionKind
from agentarea_streams.domain.mcp_events import RETRY_DELAYS
from agentarea_streams.infrastructure.di_container import StreamBusResources, setup_streams_di
from agentarea_streams.infrastructure.event_archive import S3EventArchive
from agentarea_streams.infrastructure.live import BrokerEventNotices
from agentarea_streams.infrastructure.partitions import PartitionMaintainer
from agentarea_streams.infrastructure.subscription_changes import SubscriptionChangeListener
from agentarea_triggers.batch_firing import TriggerBatchFirer
from agentarea_triggers.batches import TemporalTriggerBatches
from agentarea_triggers.channels.autoclaimer import StreamAutoclaimer
from agentarea_triggers.channels.lazy_secret_manager import LazySecretReader
from agentarea_triggers.channels.sender_admission import build_telegram_sender_admission
from agentarea_triggers.infrastructure.causation_repository import load_platform_task
from agentarea_triggers.infrastructure.reactions import TriggerExecutionReactionLog
from agentarea_triggers.stream_subscriber import ConfigurerAuthority, TriggerSubscriptionHandler

from .processor_sandbox import processor_runner

EXTERNAL_RECLAIM_MARGIN = timedelta(minutes=5)


@dataclass
class StreamRuntime:
    router: EventRouter
    events_view: EventsView
    changes: SubscriptionChangeListener
    partitions: PartitionMaintainer
    bus: StreamBusResources
    topics: list[str]
    polled: PolledItemConsumer
    polled_autoclaimer: StreamAutoclaimer
    platform: PlatformProjection
    external: ExternalDelivery
    external_autoclaimers: list[StreamAutoclaimer]
    #: What the trigger batch workflow's activities run; the trigger worker registers them.
    batches: TriggerBatchFirer
    subscriptions: list[Subscription] = field(default_factory=list)

    async def start(self) -> None:
        await self.partitions.start()
        await self.polled.start()
        await self.polled_autoclaimer.start()
        await self.changes.start(self.router.invalidate)
        await self.external.start()
        for autoclaimer in self.external_autoclaimers:
            await autoclaimer.start()
        self.subscriptions.append(
            await self.bus.events.subscribe_many(
                topics=self.topics,
                group=EVENTS_VIEW_GROUP,
                handler=self.events_view.handle,
                dead_letter_topic=dead_letter_topic(STREAM_EVENTS, EVENTS_VIEW_GROUP),
                on_dead_letter=self.events_view.give_up,
            )
        )
        self.subscriptions.append(
            await self.bus.events.subscribe_many(
                topics=self.topics,
                group=ROUTER_GROUP,
                handler=self.router.handle,
                dead_letter_topic=dead_letter_topic(STREAM_EVENTS, ROUTER_GROUP),
                on_dead_letter=self.router.give_up,
            )
        )
        self.subscriptions.append(
            await self.bus.events.subscribe_many(
                topics=[TASK_EVENTS],
                group=PLATFORM_GROUP,
                handler=self.platform.handle,
                dead_letter_topic=dead_letter_topic(TASK_EVENTS, PLATFORM_GROUP),
                on_dead_letter=self.platform.give_up,
            )
        )

    async def stop(self) -> None:
        for autoclaimer in self.external_autoclaimers:
            await autoclaimer.stop()
        await self.external.stop()
        await self.polled_autoclaimer.stop()
        await self.polled.stop()
        for subscription in self.subscriptions:
            await subscription.stop()
        self.subscriptions.clear()
        await self.changes.stop()
        await self.partitions.stop()
        await self.bus.aclose()


def build_stream_runtime(settings: Settings, dependencies: Any) -> StreamRuntime:
    if dependencies.workflow_executor is None:
        raise RuntimeError(
            "The stream router fires triggers through the workflow executor; set "
            + "dependencies.workflow_executor before building the stream runtime"
        )
    if not isinstance(settings.broker, RedisSettings):
        raise RuntimeError(
            "Event streams need the Redis broker; set AGENTAREA_BROKER=redis "
            + f"(current: {settings.broker.BROKER})"
        )
    bus = setup_streams_di(settings)
    notices = BrokerEventNotices(bus.broker)
    session_factory = get_database().async_session_factory
    authority = ConfigurerAuthority(
        graph=get_workspace_membership_graph(),
        permissions=resolve(PermissionService),
    )
    sender_admission = build_telegram_sender_admission(
        may_run=authority.may_run,
        secret_reader=LazySecretReader(dependencies.secret_manager_factory),
        redis_url=settings.broker.REDIS_URL,
        namespace=settings.streams.NAMESPACE,
        app_url=settings.app.APP_URL,
    )
    triggers = TriggerSubscriptionHandler(
        event_broker=dependencies.event_broker,
        secret_manager_factory=dependencies.secret_manager_factory,
        workflow_executor=dependencies.workflow_executor,
        authority=authority,
        max_depth=settings.streams.FORWARD_DEPTH,
        sender_admission=sender_admission,
        batches=TemporalTriggerBatches(
            dependencies.workflow_executor, task_queue=settings.triggers.QUEUE
        ),
        batch_cap=settings.triggers.BATCH_MAX_EVENTS,
    )
    router = EventRouter(
        session_factory=session_factory,
        handlers={
            SubscriptionKind.TRIGGER: triggers,
            SubscriptionKind.FORWARD: ForwardHandler(settings.streams, bus.bus),
            SubscriptionKind.EXTERNAL: ExternalSubscriptionHandler(bus.broker),
            SubscriptionKind.PROCESSOR: ProcessorHandler(
                settings.streams, bus.bus, processor_runner(settings)
            ),
        },
        reactions=TriggerExecutionReactionLog(),
        notices=notices,
    )
    consumers = settings.channel_delivery
    consumer_id = f"ingest-{socket.gethostname()}-{os.getpid()}"
    polled = PolledItemConsumer(
        bus.broker,
        session_scope=session_factory,
        ingest=ingest_source_event,
        consumer_id=consumer_id,
        block_ms=int(consumers.BLOCK.total_seconds() * 1000),
        batch_size=consumers.BATCH_SIZE,
        max_delivery_attempts=consumers.MAX_ATTEMPTS,
    )
    external = ExternalDelivery(
        broker=bus.broker,
        dedup=DedupCache(
            settings.broker.REDIS_URL,
            namespace=settings.streams.NAMESPACE,
            prefix="external-delivery",
            ttl_seconds=int(BUS_RETENTION.total_seconds()),
        ),
        session_factory=session_factory,
        secrets_for=dependencies.secret_manager_factory.create,
        readers=StreamReaders(resolve(PermissionService)),
        endpoint=WebhookEndpoint(),
        settings=settings.streams,
        consumer_id=f"external-{socket.gethostname()}-{os.getpid()}",
        block_ms=int(consumers.BLOCK.total_seconds() * 1000),
        batch_size=consumers.BATCH_SIZE,
    )
    return StreamRuntime(
        batches=TriggerBatchFirer(
            session_factory=session_factory,
            trigger_service_factory=triggers.trigger_service,
            notices=notices,
        ),
        router=router,
        events_view=EventsView(session_factory, notices),
        changes=SubscriptionChangeListener(bus.broker),
        partitions=PartitionMaintainer(
            session_factory,
            settings.streams,
            archive=S3EventArchive.from_settings() if settings.streams.ARCHIVE else None,
        ),
        bus=bus,
        topics=stream_events_partitions(settings.streams.PARTITIONS),
        polled=polled,
        polled_autoclaimer=StreamAutoclaimer(
            broker=bus.broker,
            stream=polled.stream,
            group=polled.group,
            consumer_id=consumer_id,
            handle=polled.handle,
            min_idle_ms=int(consumers.AUTOCLAIM_IDLE.total_seconds() * 1000),
            interval_seconds=consumers.AUTOCLAIM_EVERY.total_seconds(),
        ),
        platform=PlatformProjection(
            session_factory=session_factory,
            settings=settings.streams,
            bus=bus.bus,
            load_task=load_platform_task,
        ),
        external=external,
        external_autoclaimers=[
            StreamAutoclaimer(
                broker=bus.broker,
                stream=topic,
                group=DELIVERY_GROUP,
                consumer_id=f"external-{socket.gethostname()}-{os.getpid()}",
                handle=external.handler_for(topic),
                # A retry waits out its delay while pending; reclaim only past it.
                min_idle_ms=int(
                    (
                        EXTERNAL_RECLAIM_MARGIN + (RETRY_DELAYS[n - 1] if n else timedelta(0))
                    ).total_seconds()
                    * 1000
                ),
                interval_seconds=consumers.AUTOCLAIM_EVERY.total_seconds(),
            )
            for n, topic in enumerate(delivery_topics())
        ],
    )
