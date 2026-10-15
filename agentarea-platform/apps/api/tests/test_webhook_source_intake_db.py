"""Inbound webhooks go onto their stream's bus, once, and answer 202.

Set STREAMS_TEST_DATABASE_URL.
"""

import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_api.api.v1._webhook_intake import WebhookSourceIntake
from agentarea_common.broker.topics import stream_events_partition
from agentarea_common.config import get_settings
from agentarea_common.config.streams import EventStreamSettings
from agentarea_streams.application.events_view import EventsView
from agentarea_streams.domain import StreamEvent
from agentarea_streams.infrastructure.bus import StreamBus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")


class _Broker:
    """The bus's publisher and dedup cache: records what reached the broker."""

    def __init__(self):
        self.published: list[tuple[str, StreamEvent]] = []
        self.keys: set[str] = set()
        self.fail = False

    async def publish(self, event, *, topic=None):
        if self.fail:
            raise ConnectionResetError("broker went away")
        self.published.append((topic, StreamEvent.from_bus(event)))

    async def claim(self, key):
        if key in self.keys:
            return False
        self.keys.add(key)
        return True

    async def release(self, key):
        self.keys.discard(key)


class _NoSecrets:
    async def get_secret(self, name):
        return None


@pytest.fixture
async def setup():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ws, stream_id, webhook_id = str(uuid4()), uuid4(), f"wh{uuid4().hex}"
    async with maker() as session:
        await session.execute(
            text(
                "INSERT INTO streams (id, workspace_id, created_by, name, description, kind, "
                "created_at, updated_at) VALUES (:id, :ws, 'u', :n, '', 'custom', now(), now())"
            ),
            {"id": stream_id, "ws": ws, "n": f"s-{webhook_id}"},
        )
        await session.execute(
            text(
                "INSERT INTO stream_sources (id, workspace_id, created_by, stream_id, kind, "
                "webhook_id, webhook_type, allowed_methods, validation_rules, credential_key, "
                "created_at, updated_at) VALUES (:id, :ws, 'u', :s, 'webhook', :wh, 'generic', "
                "'[\"POST\"]', '{}', :k, now(), now())"
            ),
            {"id": uuid4(), "ws": ws, "s": stream_id, "wh": webhook_id, "k": uuid4()},
        )
        await session.commit()

    @asynccontextmanager
    async def scope():
        async with maker() as session:
            yield session
            await session.commit()

    def build(quota: int = 600) -> tuple[WebhookSourceIntake, _Broker]:
        broker = _Broker()
        settings = get_settings().model_copy(
            update={"streams": EventStreamSettings(WRITE_QUOTA=quota)}
        )
        lookup = maker()
        lookups.append(lookup)
        return (
            WebhookSourceIntake(
                lookup_session=lookup,
                session_scope=scope,
                secret_reader_for=lambda _s, _c: _NoSecrets(),
                bus=StreamBus(publisher=broker, dedup=broker, partitions=16),  # type: ignore[arg-type]
                event_broker=None,
                settings=settings,
            ),
            broker,
        )

    lookups: list[AsyncSession] = []
    yield SimpleNamespace(maker=maker, stream_id=stream_id, webhook_id=webhook_id, build=build)
    for lookup in lookups:
        await lookup.close()
    await engine.dispose()


async def _post(intake, webhook_id, delivery="msg_1"):
    body = {"text": "deploy"}
    return await intake.handle_webhook_request(
        webhook_id,
        "POST",
        {"content-type": "application/json", "webhook-id": delivery, "authorization": "Bearer s"},
        body,
        {},
        raw_body=json.dumps(body).encode(),
    )


async def test_a_webhook_is_published_once_and_answers_202(setup):
    intake, broker = setup.build()
    first = await _post(intake, setup.webhook_id)
    again = await _post(intake, setup.webhook_id)
    assert first["status_code"] == 202
    assert first["body"]["status"] == "accepted"
    assert again["status_code"] == 202
    assert again["body"]["status"] == "duplicate"
    assert again["body"]["event_id"] == first["body"]["event_id"]
    [(topic, event)] = broker.published
    assert topic == stream_events_partition(setup.stream_id, 16)
    assert str(event.id) == first["body"]["event_id"]
    assert event.event_key == "webhook-id:msg_1"
    assert event.type == "webhook.generic"
    assert "authorization" not in {k.lower() for k in event.data["headers"]}


async def test_an_unknown_webhook_is_refused_as_before(setup):
    intake, _ = setup.build()
    result = await _post(intake, "no-such-webhook-id-000")
    assert result["status_code"] == 400


async def test_over_the_workspace_quota_answers_429(setup):
    intake, broker = setup.build(quota=1)
    assert (await _post(intake, setup.webhook_id, "a"))["status_code"] == 202
    [(_, event)] = broker.published
    await EventsView(setup.maker).handle(event.to_bus())
    assert (await _post(intake, setup.webhook_id, "b"))["status_code"] == 429


class _Secrets:
    def __init__(self, values):
        self.values = values

    async def get_secret(self, name):
        return self.values.get(name)


async def test_a_standalone_sentry_source_is_verified_and_journaled_like_a_triggers(setup):
    ws, stream_id, source_id = str(uuid4()), uuid4(), uuid4()
    webhook_id = f"wh{uuid4().hex}"
    async with setup.maker() as session:
        await session.execute(
            text(
                "INSERT INTO streams (id, workspace_id, created_by, name, description, kind, "
                "created_at, updated_at) VALUES (:id, :ws, 'u', 'sentry', '', 'custom', now(), now())"
            ),
            {"id": stream_id, "ws": ws},
        )
        await session.execute(
            text(
                "INSERT INTO stream_sources (id, workspace_id, created_by, stream_id, kind, "
                "webhook_id, webhook_type, allowed_methods, validation_rules, credential_key, "
                "created_at, updated_at) VALUES (:id, :ws, 'u', :s, 'webhook', :wh, 'sentry', "
                "'[\"POST\"]', '{}', :id, now(), now())"
            ),
            {"id": source_id, "ws": ws, "s": stream_id, "wh": webhook_id},
        )
        await session.commit()
    secrets = _Secrets(
        {
            f"channel_cred:sentry:{source_id}": json.dumps({"client_secret": {"secret_name": "s"}}),
            "s": "sentry-secret",
        }
    )
    intake, broker = setup.build()
    intake._secret_reader_for = lambda _s, _c: secrets
    raw = json.dumps({"action": "created", "data": {"issue": {"id": "1"}}}).encode()

    async def post(signature: str):
        return await intake.handle_webhook_request(
            webhook_id,
            "POST",
            {
                "content-type": "application/json",
                "sentry-hook-resource": "issue",
                "sentry-hook-signature": signature,
                "request-id": "req-1",
            },
            json.loads(raw),
            {},
            raw_body=raw,
        )

    signature = hmac.new(b"sentry-secret", raw, hashlib.sha256).hexdigest()
    forged = await post("0" * 64)
    first = await post(signature)
    again = await post(signature)
    assert forged["status_code"] == 400
    assert first["status_code"] == 202
    assert first["body"]["status"] == "accepted"
    assert again["body"]["status"] == "duplicate"
    [(topic, event)] = broker.published
    assert topic == stream_events_partition(stream_id, 16)
    assert (event.event_key, event.type, event.source_id) == (
        "request-id:req-1",
        "issue.created",
        source_id,
    )
    assert "sentry-hook-signature" not in event.data["headers"]


async def test_a_broker_failure_answers_503_and_the_retry_is_accepted(setup):
    intake, broker = setup.build()
    broker.fail = True
    result = await _post(intake, setup.webhook_id)
    assert result["status_code"] == 503
    assert broker.published == []
    broker.fail = False
    retried = await _post(intake, setup.webhook_id)
    assert retried["status_code"] == 202
    assert retried["body"]["status"] == "accepted"
