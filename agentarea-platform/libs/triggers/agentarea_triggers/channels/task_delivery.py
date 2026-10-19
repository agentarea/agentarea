"""The ``delivery`` group on ``tasks.events``: each task event to where its task replies (ADR-0043 §7).

A run publishes its events once and does not know who reads them. This group
reads every task event, looks up where the event's task replies — the chat or
mailbox it came from (its delivery address), the caller's task webhook, its A2A
push configs — and sends the event to each of them that shows it. An address is
sent by its sender (``http``, ``telegram_live``, ``smtp``) with the reply block
of its catalog entry and its source's credentials, read in the task's workspace.

Each (event, target) is sent at least once and, short of a crash between a send
and its record, once: a target is marked delivered only after its send
succeeded, so a send that never finished — a failure, a cancellation on
shutdown, a crash — is sent again on redelivery. The message is acknowledged
once every target is delivered or dead-lettered. A target that fails for good,
or past ``max_delivery_attempts``, is copied to ``tasks.events.delivery.dlq``
naming that target; a replay of it sends to that target only.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.broker import BrokerClient, BrokerMessage, DedupCache
from agentarea_common.broker.dlq import DEAD_LETTER_REASON_FIELD
from agentarea_common.broker.topics import (
    DEAD_LETTER_RETENTION,
    DELIVERY_GROUP,
    TASK_EVENTS,
    dead_letter_topic,
)
from agentarea_common.events.adapters.redis_streams import decode
from agentarea_common.events.ports import IntegrationEvent
from agentarea_common.events.task_stream import WORKSPACE_EXTENSION
from agentarea_common.observability.propagation import consumer_span
from agentarea_common.reserved_task_parameters import DELIVERY_ADDRESS_PARAMETER
from agentarea_common.utils.task_webhook import TASK_WEBHOOK_KEY
from agentarea_execution.workflows.visibility import PresentationMode, is_visible
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from . import ChannelAdapter
from .exceptions import FatalError, RetryableError
from .http_reply import REPLY_KEY

if TYPE_CHECKING:
    from agentarea_streams.domain.source_types import Reply

logger = logging.getLogger(__name__)

DELIVERY_DLQ = dead_letter_topic(TASK_EVENTS, DELIVERY_GROUP)
# The one target a dead letter names; a replay of it sends there only.
DELIVERY_TARGET_FIELD = "delivery_target"
# The key of the target a task's delivery address makes.
ADDRESS_TARGET = "address"

# Reserved metadata keys the task webhook reports (agentarea_mcp.tool_context).
_END_USER_ID_KEY = "end_user_id"
_APP_METADATA_KEY = "app_metadata"


class DeliveryTask(Protocol):
    """What delivery reads of a task: where it replies, and whose it is."""

    @property
    def parameters(self) -> dict[str, Any] | None: ...

    @property
    def owner(self) -> str: ...

    @property
    def metadata(self) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class DeliveryTarget:
    """One place a task's events go, under a key stable for the task."""

    key: str
    channel_type: str
    config: dict[str, Any]
    presentation: str
    # Fields the target adds to the event data it is sent.
    data: dict[str, Any] = field(default_factory=dict)


def delivery_targets(task: DeliveryTask) -> list[DeliveryTarget]:
    """Where the task's events go: its delivery address, its task webhook, its A2A push configs."""
    parameters = task.parameters or {}
    metadata = task.metadata or {}
    targets: list[DeliveryTarget] = []
    address = parameters.get(DELIVERY_ADDRESS_PARAMETER)
    if isinstance(address, dict):
        if address.get("sender") and address.get("type"):
            targets.append(
                DeliveryTarget(
                    key=ADDRESS_TARGET,
                    channel_type=str(address["sender"]),
                    config=dict(address),
                    presentation=str(address.get("presentation") or PresentationMode.CONCISE),
                )
            )
        else:
            logger.error("Task has a delivery address without type or sender: %r", address)
    webhook = metadata.get(TASK_WEBHOOK_KEY)
    if isinstance(webhook, dict) and webhook.get("url"):
        targets.append(
            DeliveryTarget(
                key="task_webhook",
                channel_type="task_webhook",
                config={
                    "type": "task_webhook",
                    "url": webhook["url"],
                    "signed": bool(webhook.get("signed")),
                    "presentation": PresentationMode.SILENT,
                },
                presentation=PresentationMode.SILENT,
                data={
                    "end_user_id": metadata.get(_END_USER_ID_KEY),
                    "app_metadata": metadata.get(_APP_METADATA_KEY),
                },
            )
        )
    push_configs = parameters.get("a2a_push_configs")
    for config in push_configs if isinstance(push_configs, list) else []:
        if not isinstance(config, dict) or not config.get("id") or not config.get("url"):
            logger.error("Task has an A2A push config without id or url: %r", config)
            continue
        targets.append(
            DeliveryTarget(
                key=f"a2a:{config['id']}",
                channel_type="a2a_webhook",
                config={
                    "type": "a2a_webhook",
                    "url": config["url"],
                    "config_id": config["id"],
                    "presentation": PresentationMode.SILENT,
                },
                presentation=PresentationMode.SILENT,
            )
        )
    return targets


@dataclass(frozen=True)
class StoredReplyTargets:
    """A task's parameters and metadata, the two places its reply targets are kept, and its owner."""

    parameters: dict[str, Any] | None
    metadata: dict[str, Any] | None
    owner: str


class TaskReplyTargetReader:
    """Reads where a task replies, by the task and workspace an event names."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __call__(self, task_id: UUID, workspace_id: str) -> StoredReplyTargets | None:
        from agentarea_tasks.infrastructure.orm import TaskORM

        async with self._session_factory() as session:
            with workspace_scope(workspace_id):
                row = (
                    await session.execute(
                        select(TaskORM.parameters, TaskORM.task_metadata, TaskORM.created_by).where(
                            TaskORM.id == task_id, TaskORM.workspace_id == workspace_id
                        )
                    )
                ).one_or_none()
        if row is None:
            return None
        return StoredReplyTargets(
            parameters=row.parameters, metadata=row.task_metadata, owner=row.created_by
        )


class CatalogReplyReader:
    """The ``reply`` block of a catalog entry by its slug, cached for ``ttl_seconds``.

    Read at send time, so a corrected entry reaches tasks already running.
    """

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], ttl_seconds: float = 60.0
    ) -> None:
        self._session_factory = session_factory
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, Reply | None]] = {}

    async def __call__(self, slug: str) -> Reply | None:
        cached = self._cache.get(slug)
        now = time.monotonic()
        if cached is not None and now - cached[0] < self._ttl:
            return cached[1]
        from agentarea_streams.infrastructure.catalog_source_types import (
            CatalogSourceTypeRepository,
        )

        async with self._session_factory() as session:
            entry = await CatalogSourceTypeRepository(session).get(slug)
        reply = entry.reply if entry is not None else None
        self._cache[slug] = (now, reply)
        return reply


class _TargetFailedError(Exception):
    """A target's send failed and is tried again on redelivery."""


class TaskEventDelivery:
    """Consumer of the ``delivery`` group: send, record, then acknowledge."""

    def __init__(
        self,
        broker: BrokerClient,
        dedup: DedupCache,
        adapter_resolver: Callable[[str], ChannelAdapter | None],
        *,
        load_task: Callable[[UUID, str], Awaitable[DeliveryTask | None]],
        reply_for: Callable[[str], Awaitable[Reply | None]],
        consumer_id: str,
        block_ms: int = 5000,
        batch_size: int = 10,
        max_delivery_attempts: int = 20,
    ) -> None:
        self._broker = broker
        self._dedup = dedup
        self._resolve_adapter = adapter_resolver
        self._load_task = load_task
        self._reply_for = reply_for
        self._consumer_id = consumer_id
        self._block_ms = block_ms
        self._batch_size = batch_size
        self._max_delivery_attempts = max_delivery_attempts
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        # From "0": events published before the group first existed still go out.
        await self._broker.ensure_group(TASK_EVENTS, DELIVERY_GROUP, start="0")
        self._task = asyncio.create_task(self._run_loop(), name="task-event-delivery")
        logger.info("Task event delivery started (consumer=%s)", self._consumer_id)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        logger.info("Task event delivery stopped")

    async def _run_loop(self) -> None:
        backoff = 1.0
        while True:
            try:
                messages = await self._broker.consume(
                    TASK_EVENTS,
                    DELIVERY_GROUP,
                    self._consumer_id,
                    count=self._batch_size,
                    block_ms=self._block_ms,
                )
                for message in messages:
                    await self.handle(message)
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error(
                    "Task event delivery loop failed (retry in %.0fs)", backoff, exc_info=True
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def handle(self, message: BrokerMessage) -> None:
        """Send one task event to each of its targets; acknowledge when none is left."""
        try:
            event = decode(message.fields)
            workspace_id = event.extensions[WORKSPACE_EXTENSION]
            task_id = UUID(event.subject or "")
        except Exception as error:
            logger.error("Undecodable task event %s; dead-lettered", message.id, exc_info=True)
            await self._dead_letter(message, None, f"undecodable task event: {error}")
            await self._broker.ack(TASK_EVENTS, DELIVERY_GROUP, message.id)
            return

        with consumer_span(
            traceparent=event.traceparent,
            destination=TASK_EVENTS,
            message_id=message.id,
            consumer_group=DELIVERY_GROUP,
        ):
            await self._deliver(message, event, task_id, workspace_id)

    async def _deliver(
        self, message: BrokerMessage, event: IntegrationEvent, task_id: UUID, workspace_id: str
    ) -> None:
        task = await self._load_task(task_id, workspace_id)
        if task is None:
            # The task was deleted; nobody waits for its events any more.
            logger.info("Task %s of event %s is gone; nothing to deliver", task_id, event.id)
            await self._broker.ack(TASK_EVENTS, DELIVERY_GROUP, message.id)
            return

        only = message.fields.get(DELIVERY_TARGET_FIELD)
        targets = [
            target
            for target in delivery_targets(task)
            if (only is None or target.key == only) and is_visible(event.type, target.presentation)
        ]
        exhausted = message.delivery_count > self._max_delivery_attempts
        failed = False
        for target in targets:
            key = f"{event.id}:{target.key}"
            if await self._dedup.contains(key):
                continue
            # A replay names its target and goes past the dead-letter mark.
            if only is None and await self._dedup.contains(f"dead:{key}"):
                continue
            if exhausted:
                await self._give_up(
                    message,
                    target,
                    key,
                    f"max delivery attempts ({message.delivery_count - 1}) exceeded",
                )
                continue
            try:
                await self._send(event, str(task_id), workspace_id, task.owner, target)
            except FatalError as error:
                await self._give_up(message, target, key, f"{type(error).__name__}: {error}")
                continue
            except _TargetFailedError:
                failed = True
                continue
            await self._dedup.claim(key)
        if not failed:
            await self._broker.ack(TASK_EVENTS, DELIVERY_GROUP, message.id)

    async def _send(
        self,
        event: IntegrationEvent,
        task_id: str,
        workspace_id: str,
        owner: str,
        target: DeliveryTarget,
    ) -> None:
        adapter = self._resolve_adapter(target.channel_type)
        if adapter is None:
            # During a rolling deploy an older worker may lack a newer channel;
            # one that has it takes the message once it is reclaimed.
            logger.error(
                "No adapter for %r; event %s is redelivered", target.channel_type, event.id
            )
            raise _TargetFailedError
        payload = {
            "event_type": event.type,
            "event_id": str(event.id),
            "task_id": task_id,
            "timestamp": event.time.isoformat(),
            "data": {**event.data, **target.data},
        }
        config = {
            **target.config,
            "task_id": task_id,
            "event_type": event.type,
            "workspace_id": workspace_id,
            "owner": owner,
        }
        if target.key == ADDRESS_TARGET:
            config[REPLY_KEY] = await self._reply(str(target.config["type"]), event)
        try:
            message = adapter.format(payload, target.presentation, config)
        except FatalError:
            raise
        except Exception as error:
            raise FatalError(f"cannot format {event.type}: {error}") from error
        try:
            await adapter.send(config, message)
        except FatalError:
            raise
        except RetryableError as error:
            logger.warning(
                "Delivery of %s to %s failed; retried: %s",
                event.id,
                target.key,
                error,
                exc_info=True,
            )
            raise _TargetFailedError from error
        except Exception as error:
            logger.error(
                "Delivery of %s to %s failed unexpectedly; retried",
                event.id,
                target.key,
                exc_info=True,
            )
            raise _TargetFailedError from error

    async def _reply(self, slug: str, event: IntegrationEvent) -> Reply:
        try:
            reply = await self._reply_for(slug)
        except Exception as error:
            logger.error(
                "Reading the reply block of %r for event %s failed", slug, event.id, exc_info=True
            )
            raise _TargetFailedError from error
        if reply is None:
            raise FatalError(f"the catalog entry {slug!r} has no reply block")
        return reply

    async def _give_up(
        self, message: BrokerMessage, target: DeliveryTarget, key: str, reason: str
    ) -> None:
        await self._dead_letter(message, target, reason)
        # Not delivered, so the delivered mark stays free for a replay; this
        # one only keeps a redelivery of the message from dead-lettering twice.
        await self._dedup.claim(f"dead:{key}")

    async def _dead_letter(
        self, message: BrokerMessage, target: DeliveryTarget | None, reason: str
    ) -> None:
        fields = {
            key: value for key, value in message.fields.items() if key != DELIVERY_TARGET_FIELD
        }
        fields[DEAD_LETTER_REASON_FIELD] = reason[:500]
        if target is not None:
            fields[DELIVERY_TARGET_FIELD] = target.key
        await self._broker.submit(DELIVERY_DLQ, fields, retention=DEAD_LETTER_RETENTION)
        logger.error(
            "Task event %s dead-lettered for %s: %s",
            message.id,
            target.key if target is not None else "every target",
            reason,
        )
