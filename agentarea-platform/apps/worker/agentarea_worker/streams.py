"""Event stream runtime inside the worker: partitions, the router and the events view.

Both are consumer groups over every partition of ``streams.events`` (ADR-0043
§3, §4): the ``router`` reacts to each event, the ``events-view`` writes it into
the read model. The router's subscription cache follows the change notices the outbox
relay publishes.
"""

from dataclasses import dataclass, field
from typing import Any

from agentarea_common.auth.permission import PermissionService
from agentarea_common.broker.topics import (
    EVENTS_VIEW_GROUP,
    ROUTER_GROUP,
    STREAM_EVENTS,
    dead_letter_topic,
    stream_events_partitions,
)
from agentarea_common.config import RedisSettings, Settings
from agentarea_common.config.database import get_database
from agentarea_common.di.container import resolve
from agentarea_common.events.ports import Subscription
from agentarea_common.workspaces import get_workspace_membership_graph
from agentarea_streams.application.events_view import EventsView
from agentarea_streams.application.forward import ForwardHandler
from agentarea_streams.application.router import EventRouter
from agentarea_streams.domain import SubscriptionKind
from agentarea_streams.infrastructure.di_container import StreamBusResources, setup_streams_di
from agentarea_streams.infrastructure.partitions import PartitionMaintainer
from agentarea_streams.infrastructure.subscription_changes import SubscriptionChangeListener
from agentarea_triggers.channels.lazy_secret_manager import LazySecretReader
from agentarea_triggers.channels.sender_admission import build_telegram_sender_admission
from agentarea_triggers.infrastructure.reactions import TriggerExecutionReactionLog
from agentarea_triggers.stream_subscriber import ConfigurerAuthority, TriggerSubscriptionHandler


@dataclass
class StreamRuntime:
    router: EventRouter
    events_view: EventsView
    changes: SubscriptionChangeListener
    partitions: PartitionMaintainer
    bus: StreamBusResources
    topics: list[str]
    subscriptions: list[Subscription] = field(default_factory=list)

    async def start(self) -> None:
        await self.partitions.start()
        await self.changes.start(self.router.invalidate)
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

    async def stop(self) -> None:
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
    router = EventRouter(
        session_factory=session_factory,
        handlers={
            SubscriptionKind.TRIGGER: TriggerSubscriptionHandler(
                event_broker=dependencies.event_broker,
                secret_manager_factory=dependencies.secret_manager_factory,
                workflow_executor=dependencies.workflow_executor,
                authority=authority,
                sender_admission=sender_admission,
            ),
            SubscriptionKind.FORWARD: ForwardHandler(settings.streams, bus.bus),
        },
        reactions=TriggerExecutionReactionLog(),
    )
    return StreamRuntime(
        router=router,
        events_view=EventsView(session_factory),
        changes=SubscriptionChangeListener(settings.broker.REDIS_URL),
        partitions=PartitionMaintainer(session_factory, settings.streams),
        bus=bus,
        topics=stream_events_partitions(settings.streams.PARTITIONS),
    )
