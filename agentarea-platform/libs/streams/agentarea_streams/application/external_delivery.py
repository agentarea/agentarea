"""EXTERNAL subscribers: the router hands each match to Delivery, which POSTs it signed.

Transport (ADR-0043 §7): the router's ``EXTERNAL`` handler publishes one message
per (event, subscriber) to ``streams.external`` and records ``reacted``, so a
slow or dead endpoint never holds the router. The Delivery group on that topic
sends it by Standard Webhooks. A failed send is moved to the retry topic of its
next attempt, ``streams.external.retry.<n>``, one fixed delay per topic (30s,
2m, 10m, 30m, 1h, 2h), so each topic is in due order and its consumer only
waits for the head. Past the last retry the subscriber is marked ``failed`` and
the message goes to ``streams.external.delivery.dlq``; a refresh
(``events/subscribe``) makes it active again.

Each (event, subscriber) is claimed in ``DedupCache`` once its send
succeeded, so a redelivery or a router replay sends nothing twice. Before
every send the subscriber's right to read the stream is checked again; one
that lost it is sent a ``terminated`` envelope and removed with its secret.

The sweeper removes subscribers past their expiry, and their secrets.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from agentarea_common.auth.context import Subject, UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.broker import BrokerClient, BrokerMessage, DedupCache
from agentarea_common.broker.dlq import DEAD_LETTER_REASON_FIELD
from agentarea_common.broker.topics import (
    BUS_RETENTION,
    DEAD_LETTER_RETENTION,
    DELIVERY_GROUP,
    EXTERNAL_EVENTS,
    dead_letter_topic,
    external_retry_topic,
)
from agentarea_common.config.streams import EventStreamSettings
from agentarea_common.events.adapters.redis_streams import decode, encode
from agentarea_common.workspaces.lookup import workspace_slug_for
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..domain.enums import Verdict
from ..domain.mcp_events import RETRY_DELAYS, control_message_id, event_name, occurrence
from ..domain.models import HandlerResult, StreamEvent, SubscriptionView
from ..infrastructure.orm import StreamSubscriptionORM
from ..infrastructure.repository import StreamSubscriptionRepository, expired_external
from .stream_access import StreamReaders
from .stream_service import StreamService
from .webhook_endpoint import WebhookEndpoint

logger = logging.getLogger(__name__)

EXTERNAL_DLQ = dead_letter_topic(EXTERNAL_EVENTS, DELIVERY_GROUP)
HANDED_OVER = "handed to delivery"
_SUBSCRIPTION = "subscription"
_WORKSPACE = "workspace"
_OWNER = "owner"
_ATTEMPT = "attempt"
_DUE = "due"
SWEEP_EVERY_SECONDS = 300.0


class SecretReader(Protocol):
    async def get_secret(self, secret_name: str) -> str | None: ...

    async def delete_secret(self, secret_name: str) -> bool: ...


SecretsFor = Callable[[AsyncSession, UserContext], SecretReader]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def delivery_topics() -> list[str]:
    """The main topic, then the retry topic of each attempt in order."""
    return [EXTERNAL_EVENTS, *(external_retry_topic(n) for n in range(1, len(RETRY_DELAYS) + 1))]


class ExternalSubscriptionHandler:
    """The router's reaction to an EXTERNAL match: hand it to Delivery."""

    def __init__(self, broker: BrokerClient, *, clock: Callable[[], datetime] = _utcnow):
        self._broker = broker
        self._clock = clock

    async def handle(
        self, subscription: SubscriptionView, event: StreamEvent, session: AsyncSession
    ) -> HandlerResult:
        fields = encode(event.to_bus())
        fields.update(
            {
                _SUBSCRIPTION: str(subscription.id),
                _WORKSPACE: subscription.workspace_id,
                _OWNER: subscription.created_by,
                _ATTEMPT: "0",
                _DUE: self._clock().isoformat(),
            }
        )
        await self._broker.submit(EXTERNAL_EVENTS, fields, retention=BUS_RETENTION)
        return HandlerResult(verdict=Verdict.REACTED, reason=HANDED_OVER)


class ExternalDelivery:
    """Consumers of the Delivery group on the main and retry topics of webhook deliveries."""

    def __init__(
        self,
        *,
        broker: BrokerClient,
        dedup: DedupCache,
        session_factory: async_sessionmaker[AsyncSession],
        secrets_for: SecretsFor,
        readers: StreamReaders,
        endpoint: WebhookEndpoint,
        settings: EventStreamSettings,
        consumer_id: str,
        block_ms: int = 5000,
        batch_size: int = 10,
        clock: Callable[[], datetime] = _utcnow,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._broker = broker
        self._dedup = dedup
        self._session_factory = session_factory
        self._secrets_for = secrets_for
        self._readers = readers
        self._endpoint = endpoint
        self._settings = settings
        self._consumer_id = consumer_id
        self._block_ms = block_ms
        self._batch_size = batch_size
        self._clock = clock
        self._sleep = sleep
        self._tasks: list[asyncio.Task[None]] = []
        self._slugs: dict[str, str] = {}

    async def start(self) -> None:
        if self._tasks:
            return
        for topic in delivery_topics():
            await self._broker.ensure_group(topic, DELIVERY_GROUP, start="0")
        self._tasks = [
            asyncio.create_task(self._run(topic), name=f"external-delivery:{topic}")
            for topic in delivery_topics()
        ]
        self._tasks.append(asyncio.create_task(self._sweep_loop(), name="external-sweeper"))
        logger.info("External delivery started (consumer=%s)", self._consumer_id)

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    def handler_for(self, topic: str) -> Callable[[BrokerMessage], Awaitable[None]]:
        """Settle one message of ``topic``: wait until it is due, send, then acknowledge."""

        async def settle(message: BrokerMessage) -> None:
            await self._wait_until_due(message)
            await self.handle(topic, message)

        return settle

    async def _run(self, topic: str) -> None:
        settle = self.handler_for(topic)
        # A retry topic is in due order, so its consumer takes one at a time.
        count = self._batch_size if topic == EXTERNAL_EVENTS else 1
        backoff = 1.0
        while True:
            try:
                for message in await self._broker.consume(
                    topic, DELIVERY_GROUP, self._consumer_id, count=count, block_ms=self._block_ms
                ):
                    await settle(message)
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error(
                    "External delivery on %s failed (retry in %.0fs)", topic, backoff, exc_info=True
                )
                await self._sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _wait_until_due(self, message: BrokerMessage) -> None:
        due = message.fields.get(_DUE)
        if not due:
            return
        wait = (datetime.fromisoformat(due) - self._clock()).total_seconds()
        if wait > 0:
            await self._sleep(wait)

    async def handle(self, topic: str, message: BrokerMessage) -> None:
        try:
            event = StreamEvent.from_bus(decode(message.fields))
            subscription_id = UUID(message.fields[_SUBSCRIPTION])
            context = UserContext(
                user_id=message.fields[_OWNER], workspace_id=message.fields[_WORKSPACE]
            )
            attempt = int(message.fields[_ATTEMPT])
        except Exception as error:
            logger.error(
                "Undecodable webhook delivery %s; dead-lettered", message.id, exc_info=True
            )
            await self._dead_letter(message, f"undecodable: {error}")
            await self._broker.ack(topic, DELIVERY_GROUP, message.id)
            return
        key = f"{subscription_id}:{event.id}"
        if await self._dedup.contains(key):
            await self._broker.ack(topic, DELIVERY_GROUP, message.id)
            return
        with workspace_scope(context.workspace_id):
            async with self._session_factory() as session:
                delivered = await self._deliver(
                    session, context, subscription_id, event, message, attempt
                )
                await session.commit()
        if delivered:
            await self._dedup.claim(key)
        await self._broker.ack(topic, DELIVERY_GROUP, message.id)

    async def _deliver(
        self,
        session: AsyncSession,
        context: UserContext,
        subscription_id: UUID,
        event: StreamEvent,
        message: BrokerMessage,
        attempt: int,
    ) -> bool:
        repository = StreamSubscriptionRepository(session, context)
        subscription = await repository.get_active(subscription_id)
        if subscription is None or subscription.external_id is None:
            logger.info(
                "Subscriber %s is gone, failed or expired; event %s is not sent",
                subscription_id,
                event.id,
            )
            return False
        secrets = self._secrets_for(session, context)
        subscriber = Subject(kind="user", id=subscription.created_by)
        if not await self._readers.may_read(subscriber, subscription.stream_id):
            await self._terminate(session, context, subscription, secrets)
            return False
        secret = await secrets.get_secret(subscription.secret_name or "")
        if not secret:
            await repository.mark_failed(subscription.id)
            await self._dead_letter(message, "the subscriber's secret is missing")
            return False
        body = occurrence(event, await self._name(context.workspace_id, subscription.stream_id))
        body["cursor"] = None
        outcome = await self._endpoint.post(
            url=subscription.callback_url or "",
            secret=secret,
            subscription=subscription.external_id,
            message_id=str(event.id),
            body=body,
        )
        now = self._clock()
        await repository.record_delivery(subscription.id, at=now, error=outcome.error)
        if outcome.error is None:
            return True
        if outcome.final:
            await self._dead_letter(message, f"refused by the endpoint ({outcome.error})")
        elif attempt < len(RETRY_DELAYS):
            await self._retry(message, attempt + 1, now)
        else:
            await repository.mark_failed(subscription.id)
            await self._dead_letter(
                message,
                f"{attempt + 1} attempts failed ({outcome.error}); subscriber marked failed",
            )
        return False

    async def _retry(self, message: BrokerMessage, attempt: int, now: datetime) -> None:
        fields = dict(message.fields)
        fields[_ATTEMPT] = str(attempt)
        fields[_DUE] = (now + RETRY_DELAYS[attempt - 1]).isoformat()
        await self._broker.submit(external_retry_topic(attempt), fields, retention=BUS_RETENTION)

    async def _terminate(
        self,
        session: AsyncSession,
        context: UserContext,
        subscription: StreamSubscriptionORM,
        secrets: SecretReader,
    ) -> None:
        """The subscriber may no longer read the stream: say so, then remove it."""
        logger.info("Subscriber %s lost read access to its stream; terminated", subscription.id)
        secret = await secrets.get_secret(subscription.secret_name or "")
        if secret:
            await self._endpoint.post(
                url=subscription.callback_url or "",
                secret=secret,
                subscription=subscription.external_id or "",
                message_id=control_message_id("terminated"),
                body={
                    "type": "terminated",
                    "error": {
                        "code": -32024,
                        "message": "Forbidden",
                        "data": {"reason": "Access revoked"},
                    },
                },
            )
        await self._remove(session, context, subscription, secrets)

    async def _remove(
        self,
        session: AsyncSession,
        context: UserContext,
        subscription: StreamSubscriptionORM,
        secrets: SecretReader,
    ) -> None:
        service = StreamService(RepositoryFactory(session, context), self._settings)
        await service.unsubscribe_external(subscription)
        await secrets.delete_secret(subscription.secret_name or "")

    async def _name(self, workspace_id: str, stream_id: UUID) -> str:
        slug = self._slugs.get(workspace_id)
        if slug is None:
            slug = self._slugs[workspace_id] = await workspace_slug_for(workspace_id)
        return event_name(slug, stream_id)

    async def _dead_letter(self, message: BrokerMessage, reason: str) -> None:
        fields: dict[str, Any] = dict(message.fields)
        fields[DEAD_LETTER_REASON_FIELD] = reason[:500]
        await self._broker.submit(EXTERNAL_DLQ, fields, retention=DEAD_LETTER_RETENTION)
        logger.error("Webhook delivery %s dead-lettered: %s", message.id, reason)

    async def sweep(self) -> int:
        """Remove every subscriber past its expiry, and its secret; returns how many."""
        async with self._session_factory() as session:
            expired = await expired_external(session)
        for subscription in expired:
            context = UserContext(
                user_id=subscription.created_by, workspace_id=subscription.workspace_id
            )
            with workspace_scope(subscription.workspace_id):
                async with self._session_factory() as session:
                    row = await StreamSubscriptionRepository(session, context).get_external(
                        subscription.external_id or ""
                    )
                    if row is None:
                        continue
                    await self._remove(session, context, row, self._secrets_for(session, context))
                    await session.commit()
        if expired:
            logger.info("Removed %d expired MCP Events subscribers", len(expired))
        return len(expired)

    async def _sweep_loop(self) -> None:
        while True:
            try:
                await self.sweep()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("Sweeping expired MCP Events subscribers failed", exc_info=True)
            await self._sleep(SWEEP_EVERY_SECONDS)
