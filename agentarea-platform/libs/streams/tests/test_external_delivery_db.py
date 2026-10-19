"""MCP Events webhook subscribers against the migrated schema (ADR-0040 §5, SEP-3415).

events/subscribe makes or refreshes one EXTERNAL subscription per key, after a
challenge; the router's EXTERNAL handler hands a match to Delivery; Delivery
sends once, retries on the next topic, marks the subscriber failed past the last
retry, terminates one that lost read access, and the sweeper removes the expired. Set STREAMS_TEST_DATABASE_URL.
"""

import base64
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.base.tenant_scope import tenant_scoped_session_class, workspace_scope
from agentarea_common.broker import BrokerMessage
from agentarea_common.broker.topics import EXTERNAL_EVENTS, external_retry_topic
from agentarea_common.config.database import TenantScopeMode
from agentarea_common.config.streams import EventStreamSettings
from agentarea_streams.application import external_delivery, external_subscriptions
from agentarea_streams.application.external_delivery import (
    EXTERNAL_DLQ,
    ExternalDelivery,
    ExternalSubscriptionHandler,
)
from agentarea_streams.application.external_subscriptions import (
    ExternalSubscriptions,
    secret_name,
)
from agentarea_streams.application.stream_service import StreamService
from agentarea_streams.application.webhook_endpoint import PostOutcome
from agentarea_streams.domain import StreamEvent, SubscriptionKind, Verdict
from agentarea_streams.domain.keys import event_id_for
from agentarea_streams.domain.mcp_events import ErrorCode, EventArguments, EventsError
from agentarea_streams.infrastructure.orm import StreamSubscriptionORM
from agentarea_streams.infrastructure.repository import StreamSubscriptionRepository
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")
GRANT = "agentarea_common.base.workspace_scoped_repository.grant_resource_owner"
URL = "https://hooks.example/in"
SECRET = "whsec_" + base64.b64encode(b"q" * 32).decode()  # pragma: allowlist secret


class _Endpoint:
    def __init__(self):
        self.challenges: list[str] = []
        self.posts: list[dict] = []
        self.outcomes: list[PostOutcome] = []

    async def check(self, url):
        return None

    async def challenge(self, *, url, secret, subscription):
        self.challenges.append(url)

    async def post(self, *, url, secret, subscription, message_id, body):
        self.posts.append({"url": url, "secret": secret, "id": message_id, "body": body})
        return self.outcomes.pop(0) if self.outcomes else PostOutcome(error=None)


class _Secrets:
    def __init__(self):
        self.values: dict[str, str] = {}

    async def set_secret(self, name, value):
        self.values[name] = value

    async def get_secret(self, name):
        return self.values.get(name)

    async def delete_secret(self, name):
        return self.values.pop(name, None) is not None


class _Broker:
    def __init__(self):
        self.topics: dict[str, list[dict[str, str]]] = {}
        self.acked: list[str] = []

    async def submit(self, stream, fields, *, retention):
        self.topics.setdefault(stream, []).append(dict(fields))
        return f"{len(self.topics[stream])}-0"

    async def ack(self, stream, group, message_id):
        self.acked.append(message_id)


class _Dedup:
    def __init__(self):
        self.keys: set[str] = set()

    async def contains(self, key):
        return key in self.keys

    async def claim(self, key):
        self.keys.add(key)
        return True


class _Readers:
    def __init__(self):
        self.allowed = True

    async def may_read(self, user_id, stream_id):
        return self.allowed


@pytest.fixture
async def world(monkeypatch):
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        sync_session_class=tenant_scoped_session_class(TenantScopeMode.ENFORCE),
        expire_on_commit=False,
    )
    raw = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    secrets = _Secrets()
    endpoint = _Endpoint()
    broker = _Broker()
    readers = _Readers()

    async def slug_for(workspace_id):
        return "ws"

    monkeypatch.setattr(external_delivery, "workspace_slug_for", slug_for)

    with workspace_scope(ctx.workspace_id), patch(GRANT, new=AsyncMock()):
        async with maker() as session:
            stream = await StreamService(
                RepositoryFactory(session, ctx), EventStreamSettings()
            ).create_stream(name="orders", description="")
            await session.commit()

    async def subscribe(url=URL, arguments=None, ttl_ms=600_000):
        with workspace_scope(ctx.workspace_id):
            async with maker() as session:
                result = await ExternalSubscriptions(
                    StreamService(RepositoryFactory(session, ctx), EventStreamSettings()),
                    secrets,
                    endpoint,
                ).subscribe(
                    stream_id=stream.id,
                    subscriber="user:u",
                    url=url,
                    secret=SECRET,
                    arguments=arguments or EventArguments(),
                    ttl_ms=ttl_ms,
                )
                await session.commit()
        return result

    async def unsubscribe(url=URL, arguments=None):
        with workspace_scope(ctx.workspace_id):
            async with maker() as session:
                await ExternalSubscriptions(
                    StreamService(RepositoryFactory(session, ctx), EventStreamSettings()),
                    secrets,
                    endpoint,
                ).unsubscribe(
                    stream_id=stream.id,
                    subscriber="user:u",
                    url=url,
                    arguments=arguments or EventArguments(),
                )
                await session.commit()

    async def row(external_id):
        with workspace_scope(ctx.workspace_id):
            async with maker() as session:
                return await StreamSubscriptionRepository(session, ctx).get_external(external_id)

    async def set_columns(external_id, **values):
        async with raw() as session:
            await session.execute(
                update(StreamSubscriptionORM)
                .where(StreamSubscriptionORM.external_id == external_id)
                .values(**values)
            )
            await session.commit()

    delivery = ExternalDelivery(
        broker=broker,
        dedup=_Dedup(),
        session_factory=maker,
        secrets_for=lambda session, context: secrets,
        readers=readers,
        endpoint=endpoint,
        settings=EventStreamSettings(),
        consumer_id="test",
        clock=lambda: datetime.now(UTC),
    )
    yield SimpleNamespace(
        maker=maker,
        ctx=ctx,
        stream=stream,
        secrets=secrets,
        endpoint=endpoint,
        broker=broker,
        readers=readers,
        delivery=delivery,
        subscribe=subscribe,
        unsubscribe=unsubscribe,
        row=row,
        set_columns=set_columns,
    )
    async with raw() as session:
        for table in ("streams", "event_outbox"):
            await session.execute(
                text(f"DELETE FROM {table} WHERE workspace_id = :ws"),  # noqa: S608
                {"ws": ctx.workspace_id},
            )
        await session.commit()
    await engine.dispose()


def _event(world, key="o1", *, kind="order.created", received_at=None) -> StreamEvent:
    return StreamEvent(
        id=event_id_for(world.stream.id, key),
        type=kind,
        source="test",
        data={"body": {"id": key}},
        stream_id=world.stream.id,
        workspace_id=world.ctx.workspace_id,
        created_by="u",
        event_key=key,
        received_at=received_at or datetime.now(UTC),
    )


async def _view(world, external_id):
    from agentarea_streams.application.router import subscription_view

    return subscription_view(await world.row(external_id))


async def _hand_over(world, external_id, event) -> BrokerMessage:
    with workspace_scope(world.ctx.workspace_id):
        async with world.maker() as session:
            result = await ExternalSubscriptionHandler(world.broker).handle(
                await _view(world, external_id), event, session
            )
    assert result.verdict is Verdict.REACTED
    fields = world.broker.topics[EXTERNAL_EVENTS][-1]
    return BrokerMessage(id="m1", fields=fields, stream=EXTERNAL_EVENTS)


async def test_subscribe_challenges_once_per_endpoint_and_refreshes_in_place(world):
    first = await world.subscribe()
    assert first.id.startswith("sub_")
    assert first.delivery_status is None
    assert world.endpoint.challenges == [URL]
    assert world.secrets.values[secret_name(first.id)] == SECRET
    row = await world.row(first.id)
    assert row.kind == SubscriptionKind.EXTERNAL.value
    assert row.subscriber == "user:u"
    assert row.callback_url == URL

    again = await world.subscribe(ttl_ms=900_000)
    assert again.id == first.id
    assert again.delivery_status == {"active": True, "lastDeliveryAt": None, "lastError": None}
    assert again.refresh_before > first.refresh_before
    other = await world.subscribe(arguments=EventArguments(kind="order"))
    assert other.id != first.id
    assert world.endpoint.challenges == [URL]


async def test_unsubscribe_removes_the_subscriber_and_its_secret(world):
    subscribed = await world.subscribe()
    await world.unsubscribe()
    assert await world.row(subscribed.id) is None
    assert secret_name(subscribed.id) not in world.secrets.values
    with pytest.raises(EventsError) as raised:
        await world.unsubscribe()
    assert raised.value.code == ErrorCode.NOT_FOUND


async def test_the_workspace_limit_is_resource_exhausted(world, monkeypatch):
    monkeypatch.setattr(external_subscriptions, "MAX_SUBSCRIPTIONS_PER_WORKSPACE", 1)
    await world.subscribe()
    with pytest.raises(EventsError) as raised:
        await world.subscribe(url="https://hooks.example/other")
    assert raised.value.code == ErrorCode.RESOURCE_EXHAUSTED
    assert raised.value.data == {"limit": "subscriptions", "max": 1}


async def test_a_delivery_is_sent_once_as_an_occurrence(world):
    subscribed = await world.subscribe()
    event = _event(world)
    message = await _hand_over(world, subscribed.id, event)
    await world.delivery.handle(EXTERNAL_EVENTS, message)
    await world.delivery.handle(EXTERNAL_EVENTS, message)
    assert len(world.endpoint.posts) == 1
    sent = world.endpoint.posts[0]
    assert sent["id"] == str(event.id)
    assert sent["secret"] == SECRET
    assert sent["body"]["name"] == f"ws/{world.stream.id}"
    assert sent["body"]["eventId"] == str(event.id)
    assert sent["body"]["data"]["kind"] == "order.created"
    assert world.broker.acked == ["m1", "m1"]
    assert (await world.row(subscribed.id)).last_delivery_at is not None


async def test_a_failed_send_waits_on_the_next_retry_topic_then_fails_the_subscriber(world):
    subscribed = await world.subscribe()
    message = await _hand_over(world, subscribed.id, _event(world))
    world.endpoint.outcomes = [PostOutcome(error="http_5xx")]
    await world.delivery.handle(EXTERNAL_EVENTS, message)
    retry = world.broker.topics[external_retry_topic(1)][0]
    assert retry["attempt"] == "1"
    due = datetime.fromisoformat(retry["due"]) - datetime.now(UTC)
    assert timedelta(seconds=25) < due <= timedelta(seconds=30)
    row = await world.row(subscribed.id)
    assert (row.last_error, row.status) == ("http_5xx", "active")
    assert row.failed_since is not None

    last = BrokerMessage(id="m7", fields={**retry, "attempt": "6"}, stream=external_retry_topic(6))
    world.endpoint.outcomes = [PostOutcome(error="timeout")]
    await world.delivery.handle(external_retry_topic(6), last)
    assert (await world.row(subscribed.id)).status == "failed"
    assert len(world.broker.topics[EXTERNAL_DLQ]) == 1
    assert external_retry_topic(7) not in world.broker.topics

    refreshed = await world.subscribe()
    assert refreshed.delivery_status is not None
    assert refreshed.delivery_status["active"] is False
    assert (await world.row(subscribed.id)).status == "active"


async def test_a_refused_event_is_not_retried(world):
    subscribed = await world.subscribe()
    message = await _hand_over(world, subscribed.id, _event(world))
    world.endpoint.outcomes = [PostOutcome(error="http_4xx", final=True)]
    await world.delivery.handle(EXTERNAL_EVENTS, message)
    assert external_retry_topic(1) not in world.broker.topics
    assert len(world.broker.topics[EXTERNAL_DLQ]) == 1
    assert (await world.row(subscribed.id)).status == "active"


async def test_a_subscriber_that_lost_read_access_is_terminated(world):
    subscribed = await world.subscribe()
    message = await _hand_over(world, subscribed.id, _event(world))
    world.readers.allowed = False
    await world.delivery.handle(EXTERNAL_EVENTS, message)
    assert [p["body"].get("type") for p in world.endpoint.posts] == ["terminated"]
    assert world.endpoint.posts[0]["body"]["error"]["code"] == -32024
    assert await world.row(subscribed.id) is None
    assert secret_name(subscribed.id) not in world.secrets.values


async def test_the_sweeper_removes_expired_subscribers_and_their_secrets(world):
    expired = await world.subscribe()
    kept = await world.subscribe(url="https://hooks.example/kept")
    await world.set_columns(expired.id, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    await world.delivery.sweep()
    assert await world.row(expired.id) is None
    assert secret_name(expired.id) not in world.secrets.values
    assert await world.row(kept.id) is not None
    with workspace_scope(world.ctx.workspace_id):
        async with world.maker() as session:
            remaining = await session.execute(
                select(StreamSubscriptionORM.external_id).where(
                    StreamSubscriptionORM.stream_id == world.stream.id
                )
            )
    assert set(remaining.scalars()) == {kept.id}
