"""Event stream runtime inside the worker: partitions, wake listener, dispatcher."""

from dataclasses import dataclass
from typing import Any

from agentarea_common.auth.permission import PermissionService
from agentarea_common.config import RedisSettings, Settings
from agentarea_common.config.database import get_database
from agentarea_common.di.container import resolve
from agentarea_common.workspaces import get_workspace_membership_graph
from agentarea_streams.application.dispatcher import StreamDispatcher
from agentarea_streams.application.forward import ForwardHandler
from agentarea_streams.domain import SubscriptionKind
from agentarea_streams.infrastructure.di_container import setup_streams_di
from agentarea_streams.infrastructure.partitions import PartitionMaintainer
from agentarea_streams.infrastructure.waker import RedisStreamWaker, RedisWakeListener
from agentarea_triggers.stream_subscriber import ConfigurerAuthority, TriggerSubscriptionHandler


@dataclass
class StreamRuntime:
    dispatcher: StreamDispatcher
    listener: RedisWakeListener
    partitions: PartitionMaintainer
    waker: RedisStreamWaker

    async def start(self) -> None:
        await self.partitions.start()
        await self.listener.start(self.dispatcher.notify)
        await self.dispatcher.start()

    async def stop(self) -> None:
        await self.dispatcher.stop()
        await self.listener.stop()
        await self.partitions.stop()
        await self.waker.aclose()


def build_stream_runtime(settings: Settings, dependencies: Any) -> StreamRuntime:
    if dependencies.workflow_executor is None:
        raise RuntimeError(
            "The stream dispatcher fires triggers through the workflow executor; set "
            + "dependencies.workflow_executor before building the stream runtime"
        )
    if not isinstance(settings.broker, RedisSettings):
        raise RuntimeError(
            "Event streams need the Redis broker; set AGENTAREA_BROKER=redis "
            + f"(current: {settings.broker.BROKER})"
        )
    waker = setup_streams_di(settings)
    session_factory = get_database().async_session_factory
    dispatcher = StreamDispatcher(
        session_factory=session_factory,
        settings=settings.streams,
        handlers={
            SubscriptionKind.TRIGGER: TriggerSubscriptionHandler(
                event_broker=dependencies.event_broker,
                secret_manager_factory=dependencies.secret_manager_factory,
                workflow_executor=dependencies.workflow_executor,
                authority=ConfigurerAuthority(
                    graph=get_workspace_membership_graph(),
                    permissions=resolve(PermissionService),
                ),
            ),
            SubscriptionKind.FORWARD: ForwardHandler(settings.streams),
        },
        waker=waker,
    )
    return StreamRuntime(
        dispatcher=dispatcher,
        listener=RedisWakeListener(settings.broker.REDIS_URL),
        partitions=PartitionMaintainer(session_factory, settings.streams),
        waker=waker,
    )
