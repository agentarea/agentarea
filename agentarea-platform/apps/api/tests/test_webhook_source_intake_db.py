"""Inbound webhooks are verified by their catalog entry, go onto their stream's bus once, and answer 202.

Set STREAMS_TEST_DATABASE_URL.
"""

import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_api.api.v1._webhook_intake import WebhookSourceIntake
from agentarea_common.broker.topics import stream_events_partition
from agentarea_common.config import get_settings
from agentarea_common.config.streams import EventStreamSettings
from agentarea_streams.domain import StreamEvent
from agentarea_streams.infrastructure.bus import StreamBus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")

CATALOG = Path(__file__).resolve().parents[4] / "data" / "catalog" / "source-types.json"
SIGNING_SECRET = "generic-secret"  # noqa: S105 - a test value


def _catalog_entry(slug: str) -> dict:
    entries = json.loads(CATALOG.read_text())["source_types"]
    return next(entry for entry in entries if entry["slug"] == slug)


async def _ensure_source_type(session: AsyncSession, slug: str) -> None:
    """The catalog row a source of ``slug`` is read by, as the registry sync writes it."""
    found = await session.execute(
        text(
            "SELECT 1 FROM registry_items WHERE registry_type = 'source_types' "
            "AND external_id = :slug AND registry_active"
        ),
        {"slug": slug},
    )
    if found.first() is not None:
        return
    registry_id = str(uuid4())
    await session.execute(
        text(
            "INSERT INTO registries (id, name, registry_type, source_type, source_url, "
            "is_active, created_at, updated_at) "
            "VALUES (:id, :name, 'source_types', 'managed', 'x', true, now(), now())"
        ),
        {"id": registry_id, "name": f"test-{registry_id}"},
    )
    await session.execute(
        text(
            "INSERT INTO registry_items (id, registry_id, external_id, name, spec, tags, "
            "sort_key, featured, registry_type, registry_priority, registry_active, "
            "created_at, updated_at) "
            "SELECT :id, r.id, :slug, :slug, CAST(:spec AS jsonb), '[]'::jsonb, :slug, false, "
            "r.registry_type, r.recommendation_priority, r.is_active, now(), now() "
            "FROM registries r WHERE r.id = :registry_id"
        ),
        {
            "id": str(uuid4()),
            "registry_id": registry_id,
            "slug": slug,
            "spec": json.dumps(_catalog_entry(slug)),
        },
    )


async def _add_source(session, *, ws, stream_id, source_id, webhook_id, slug) -> None:
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
            "webhook_id, webhook_type, webhook_config, credential_key, created_at, updated_at) "
            "VALUES (:id, :ws, 'u', :s, 'webhook', :wh, :slug, '{}', :id, now(), now())"
        ),
        {"id": source_id, "ws": ws, "s": stream_id, "wh": webhook_id, "slug": slug},
    )
    await _ensure_source_type(session, slug)


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


class _Secrets:
    def __init__(self, values):
        self.values = values
        self.fail = False

    async def get_secret(self, name):
        if self.fail:
            raise ConnectionError("secret store went away")
        return self.values.get(name)


class _Files:
    def __init__(self):
        self.stored: dict[str, bytes] = {}

    async def put(self, workspace_id, path, data, content_type=None):
        self.stored[path] = data


@pytest.fixture
async def setup():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ws, stream_id, source_id = str(uuid4()), uuid4(), uuid4()
    webhook_id = f"wh{uuid4().hex}"
    async with maker() as session:
        await _add_source(
            session,
            ws=ws,
            stream_id=stream_id,
            source_id=source_id,
            webhook_id=webhook_id,
            slug="generic_webhook",
        )
        await session.commit()
    secrets = _Secrets(
        {
            f"channel_cred:generic_webhook:{source_id}": json.dumps(
                {"signing_secret": SIGNING_SECRET}
            )
        }
    )

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
        return (
            WebhookSourceIntake(
                session_scope=scope,
                secret_reader_for=lambda _s, _c: secrets,
                bus=StreamBus(  # type: ignore[arg-type]
                    publisher=broker, dedup=broker, quota=_Quota(), partitions=16
                ),
                files=_Files(),
                settings=settings,
            ),
            broker,
        )

    yield SimpleNamespace(
        maker=maker,
        stream_id=stream_id,
        source_id=source_id,
        webhook_id=webhook_id,
        secrets=secrets,
        build=build,
    )
    await engine.dispose()


class _Quota:
    def __init__(self) -> None:
        self.count = 0

    async def take(self, workspace_id, limit, now):
        if self.count + 1 > limit:
            return False
        self.count += 1
        return True


async def _post(intake, webhook_id, delivery="msg_1", *, secret=SIGNING_SECRET, method="POST"):
    body = {"text": "deploy"}
    raw = json.dumps(body).encode()
    return await intake.handle_webhook_request(
        webhook_id,
        method,
        {
            "content-type": "application/json",
            "webhook-id": delivery,
            "authorization": "Bearer s",
            "x-webhook-signature": hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(),
        },
        body,
        raw,
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
    assert event.event_key == "msg_1"
    assert event.type == "webhook"
    assert (event.source_id, event.source_type) == (setup.source_id, "generic_webhook")
    headers = {k.lower() for k in event.data["headers"]}
    assert "authorization" not in headers
    assert "x-webhook-signature" not in headers
    assert event.data["body"] == {"text": "deploy"}


async def test_an_unknown_webhook_answers_404(setup):
    intake, _ = setup.build()
    result = await _post(intake, "no-such-webhook-id-000")
    assert result["status_code"] == 404


async def test_a_non_post_request_answers_405(setup):
    intake, broker = setup.build()
    result = await _post(intake, setup.webhook_id, method="GET")
    assert result["status_code"] == 405
    assert broker.published == []


async def test_a_request_signed_with_another_secret_answers_401(setup):
    intake, broker = setup.build()
    result = await _post(intake, setup.webhook_id, secret="not-the-secret")  # noqa: S106
    assert result["status_code"] == 401
    assert broker.published == []


async def test_an_unreachable_secret_store_answers_503(setup):
    intake, broker = setup.build()
    setup.secrets.fail = True
    result = await _post(intake, setup.webhook_id)
    assert result["status_code"] == 503
    assert broker.published == []


async def test_over_the_workspace_quota_answers_429(setup):
    intake, broker = setup.build(quota=1)
    assert (await _post(intake, setup.webhook_id, "a"))["status_code"] == 202
    # Counted as it was admitted: no read model has to have seen the first one.
    assert (await _post(intake, setup.webhook_id, "b"))["status_code"] == 429


async def test_a_sentry_source_is_verified_by_its_entry_with_a_referenced_secret(setup):
    ws, stream_id, source_id = str(uuid4()), uuid4(), uuid4()
    webhook_id = f"wh{uuid4().hex}"
    async with setup.maker() as session:
        await _add_source(
            session,
            ws=ws,
            stream_id=stream_id,
            source_id=source_id,
            webhook_id=webhook_id,
            slug="sentry",
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
            raw,
        )

    signature = hmac.new(b"sentry-secret", raw, hashlib.sha256).hexdigest()
    forged = await post("0" * 64)
    first = await post(signature)
    again = await post(signature)
    assert forged["status_code"] == 401
    assert first["status_code"] == 202
    assert first["body"]["status"] == "accepted"
    assert again["body"]["status"] == "duplicate"
    [(topic, event)] = broker.published
    assert topic == stream_events_partition(stream_id, 16)
    assert (event.event_key, event.type, event.source_id, event.source_type) == (
        "req-1",
        "issue.created",
        source_id,
        "sentry",
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
