"""A source added to a stream: a catalog entry's credentials by reference, never echoed."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_api.api.deps.services import get_secret_catalog_service, get_secret_manager
from agentarea_api.api.v1.streams import get_stream_service
from agentarea_api.main import app
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.openfga_permission import OpenFGAPermissionService
from agentarea_common.auth.permission import PermissionService
from agentarea_common.config.database import get_db_session
from agentarea_common.di.container import get_container
from agentarea_common.rebac.openfga_client import OpenFGAClient
from agentarea_secrets.catalog_service import SecretAccessDeniedError
from agentarea_streams.domain import StreamInUseError, StreamSourceNotFoundError
from agentarea_streams.domain.source_types import SourceTypeEntry
from httpx import ASGITransport, AsyncClient

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
STREAM = uuid4()
BASE = f"/v1/workspaces/acme/streams/{STREAM}"
CATALOG = Path(__file__).resolve().parents[4] / "data" / "catalog" / "source-types.json"
ENTRIES = {
    entry.slug: entry
    for entry in (
        SourceTypeEntry.model_validate(raw)
        for raw in json.loads(CATALOG.read_text())["source_types"]
    )
}


class _Catalog:
    """The shipped catalog, as the registry sync writes it to registry_items."""

    def __init__(self, _session):
        pass

    async def get(self, slug):
        return ENTRIES.get(slug)

    async def list_entries(self):
        return sorted(ENTRIES.values(), key=lambda e: e.name.lower())


class _Secrets:
    def __init__(self, values: dict[str, str] | None = None):
        self.values = dict(values or {})
        self.deleted: list[str] = []

    async def get_secret(self, name):
        return self.values.get(name)

    async def has_secret(self, name):
        return name in self.values

    async def set_secret(self, name, value):
        self.values[name] = value

    async def delete_secret(self, name):
        self.deleted.append(name)
        return self.values.pop(name, None) is not None


def _row(source_type: str, *, kind="webhook", webhook_config=None, event_templates=None):
    source_id = uuid4()
    return SimpleNamespace(
        id=source_id,
        kind=kind,
        webhook_id="wh-abc" if kind == "webhook" else None,
        webhook_type=source_type,
        webhook_config=webhook_config or {},
        credential_key=source_id,
        event_templates=event_templates,
        polled_at=None,
        poll_error=None,
        registered_url=None,
        created_at=NOW,
    )


@pytest.fixture
def graph():
    client = AsyncMock(spec=OpenFGAClient)
    client.check.return_value = SimpleNamespace(allowed=True)
    client.list_objects.return_value = []
    container = get_container()
    container.register_singleton(OpenFGAClient, client)
    container.register_singleton(PermissionService, OpenFGAPermissionService(client))
    yield client
    container.clear()


@pytest.fixture
def env(monkeypatch):
    service = AsyncMock()
    service.add_source.side_effect = lambda **kw: _row(
        kw["source_type"],
        kind=kw["kind"].value,
        webhook_config=kw["webhook_config"],
        event_templates=kw["event_templates"],
    )
    secrets = _Secrets({"gh-hook": "from-catalog", "bot": "123:abc"})
    catalog = AsyncMock()
    overrides = {
        get_stream_service: lambda: service,
        get_secret_manager: lambda: secrets,
        get_secret_catalog_service: lambda: catalog,
        get_user_context: lambda: UserContext(user_id="u", workspace_id="ws"),
        get_db_session: lambda: AsyncMock(),
    }
    app.dependency_overrides.update(overrides)
    for module in ("agentarea_api.api.v1.streams", "agentarea_api.api.v1._stream_sources"):
        monkeypatch.setattr(f"{module}.CatalogSourceTypeRepository", _Catalog)
    monkeypatch.setattr(
        "agentarea_api.api.v1.streams.public_webhook_url",
        lambda wid: f"https://api.example/webhooks/{wid}",
    )
    yield SimpleNamespace(service=service, secrets=secrets, catalog=catalog)
    for dep in overrides:
        app.dependency_overrides.pop(dep, None)


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def _stored(env, source_type: str, source_id: str) -> dict:
    return json.loads(env.secrets.values[f"channel_cred:{source_type}:{source_id}"])


async def test_the_source_types_come_from_the_catalog(client, env, graph):
    response = await client.get("/v1/workspaces/acme/streams/source-types")
    assert response.status_code == 200, response.text
    types = {t["slug"]: t for t in response.json()}
    assert {
        "generic_webhook",
        "github",
        "sentry",
        "yookassa",
        "stripe",
        "telegram",
        "slack",
        "email",
    } <= set(types)
    assert [f["key"] for f in types["sentry"]["credentials"]] == ["client_secret"]
    assert [f["key"] for f in types["yookassa"]["config"]] == ["shop_id"]
    assert types["yookassa"]["verification_scheme"] == "api_lookup"
    assert "payment.succeeded" in types["yookassa"]["events"]
    assert types["telegram"]["delivery"] == "both"
    assert types["telegram"]["continues_sessions"] is True
    assert types["github"]["icon_url"].endswith("/channels/github.svg")


async def test_a_typed_secret_is_stored_under_the_source_and_never_returned(client, env, graph):
    response = await client.post(
        f"{BASE}/sources",
        json={"source_type": "sentry", "credentials": {"client_secret": "s3cret"}},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["webhook_url"] == "https://api.example/webhooks/wh-abc"
    assert body["source_type"] == "sentry"
    assert body["issued"] == {}
    assert "s3cret" not in response.text
    assert _stored(env, "sentry", body["id"]) == {"client_secret": "s3cret"}
    kwargs = env.service.add_source.await_args.kwargs
    assert kwargs["webhook_config"] == {}
    assert "s3cret" not in json.dumps(kwargs, default=str)


async def test_a_picked_workspace_secret_is_held_by_name_and_recorded_as_used(client, env, graph):
    secret_id = uuid4()
    env.catalog.get_for_use.return_value = SimpleNamespace(id=secret_id, secret_name="gh-hook")
    response = await client.post(
        f"{BASE}/sources",
        json={
            "source_type": "github",
            "credentials": {"webhook_secret": {"secret_id": str(secret_id)}},
        },
    )
    assert response.status_code == 201, response.text
    source_id = response.json()["id"]
    assert _stored(env, "github", source_id) == {"webhook_secret": {"secret_name": "gh-hook"}}
    env.catalog.add_reference.assert_awaited_once_with(
        secret_id, "stream_source", source_id, "webhook_secret"
    )
    assert "from-catalog" not in env.secrets.values[f"channel_cred:github:{source_id}"]


async def test_a_secret_the_caller_may_not_use_is_refused(client, env, graph):
    env.catalog.get_for_use.side_effect = SecretAccessDeniedError("only its creator")
    response = await client.post(
        f"{BASE}/sources",
        json={"source_type": "github", "credentials": {"webhook_secret": {"secret_id": str(uuid4())}}},
    )
    assert response.status_code == 403
    env.service.add_source.assert_not_called()


@pytest.mark.parametrize(
    ("payload", "says"),
    [
        ({"source_type": "sentry"}, "needs client_secret"),
        ({"source_type": "github", "credentials": {"webhook_secret": ""}}, "webhook_secret is empty"),
        ({"source_type": "yookassa", "credentials": {"secret_key": "k"}}, "needs shop_id"),
        ({"source_type": "yookassa", "config": {"shop_id": "1"}}, "needs secret_key"),
        (
            {"source_type": "github", "credentials": {"webhook_secret": "x", "token": "y"}},
            "no credential token",
        ),
        (
            {"source_type": "github", "credentials": {"webhook_secret": "x"}, "config": {"a": "b"}},
            "no setting a",
        ),
        ({"source_type": "gitlab"}, "Unknown source type"),
        (
            {"source_type": "github", "kind": "poll", "credentials": {"webhook_secret": "x"}},
            "not poll",
        ),
        # Accepted once, then every delivery failed verification on a digest
        # the verifier has no hashlib function for.
        (
            {"source_type": "generic_webhook", "config": {"algorithm": "sha-256"}},
            "cannot verify with these settings",
        ),
        (
            {"source_type": "generic_webhook", "config": {"algorithm": "md5"}},
            "cannot verify with these settings",
        ),
    ],
)
async def test_a_source_its_entry_cannot_take_is_refused(client, env, graph, payload, says):
    response = await client.post(f"{BASE}/sources", json=payload)
    assert response.status_code == 422, response.text
    assert says in response.json()["detail"]
    env.service.add_source.assert_not_called()
    assert env.secrets.values == {"gh-hook": "from-catalog", "bot": "123:abc"}


@pytest.mark.parametrize("source_type", ["generic_webhook", "email"])
async def test_a_source_without_its_optional_secret_is_issued_one_shown_once(
    client, env, graph, source_type
):
    response = await client.post(f"{BASE}/sources", json={"source_type": source_type})
    assert response.status_code == 201, response.text
    body = response.json()
    issued = body["issued"]["signing_secret"]
    assert issued and len(issued) >= 32
    assert _stored(env, source_type, body["id"]) == {"signing_secret": issued}
    env.service.list_sources.return_value = [_row(source_type)]
    listed = await client.get(f"{BASE}/sources")
    assert issued not in listed.text


@pytest.mark.parametrize("algorithm", ["sha1", "sha256", "sha384", "sha512"])
async def test_a_generic_source_takes_every_digest_the_verifier_supports(
    client, env, graph, algorithm
):
    response = await client.post(
        f"{BASE}/sources",
        json={"source_type": "generic_webhook", "config": {"algorithm": algorithm}},
    )
    assert response.status_code == 201, response.text
    assert env.service.add_source.await_args.kwargs["webhook_config"] == {"algorithm": algorithm}


async def test_a_generic_source_keeps_its_own_event_templates(client, env, graph):
    response = await client.post(
        f"{BASE}/sources",
        json={
            "source_type": "generic_webhook",
            "event_templates": {"kind": "{body:type}", "key": "{body:id}"},
        },
    )
    assert response.status_code == 201, response.text
    assert env.service.add_source.await_args.kwargs["event_templates"] == {
        "kind": "{body:type}",
        "key": "{body:id}",
    }
    assert response.json()["event_templates"] == {"kind": "{body:type}", "key": "{body:id}"}


async def test_a_secret_given_for_an_optional_field_is_kept_and_never_returned(client, env, graph):
    response = await client.post(
        f"{BASE}/sources",
        json={"source_type": "email", "credentials": {"signing_secret": "mine"}},
    )
    assert response.status_code == 201, response.text
    assert response.json()["issued"] == {}
    assert "mine" not in response.text
    assert _stored(env, "email", response.json()["id"]) == {"signing_secret": "mine"}


async def test_yookassa_settings_are_kept_on_the_source_for_the_verifier(client, env, graph):
    response = await client.post(
        f"{BASE}/sources",
        json={
            "source_type": "yookassa",
            "credentials": {"secret_key": "live_x"},
            "config": {"shop_id": "506751"},
        },
    )
    assert response.status_code == 201, response.text
    assert env.service.add_source.await_args.kwargs["webhook_config"] == {"shop_id": "506751"}
    assert _stored(env, "yookassa", response.json()["id"]) == {"secret_key": "live_x"}


async def test_a_telegram_source_is_issued_its_token_and_left_to_the_reconciler(
    client, env, graph
):
    secret_id = uuid4()
    env.catalog.get_for_use.return_value = SimpleNamespace(id=secret_id, secret_name="bot")
    response = await client.post(
        f"{BASE}/sources",
        json={"source_type": "telegram", "credentials": {"bot_token": {"secret_id": str(secret_id)}}},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    stored = _stored(env, "telegram", body["id"])
    assert stored["bot_token"] == {"secret_name": "bot"}
    assert stored["secret_token"] == body["issued"]["secret_token"]
    assert body["registered"] is False


async def test_a_telegram_poll_source_has_no_webhook_url(client, env, graph):
    response = await client.post(
        f"{BASE}/sources",
        json={"source_type": "telegram", "kind": "poll", "credentials": {"bot_token": "123:abc"}},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["kind"], body["webhook_id"], body["webhook_url"]) == ("poll", None, None)
    assert env.service.add_source.await_args.kwargs["kind"].value == "poll"


async def test_deleting_a_source_drops_its_credentials_and_references(client, env, graph):
    row = _row("sentry")
    env.service.delete_source.return_value = row
    env.secrets.values[f"channel_cred:sentry:{row.id}"] = "{}"
    response = await client.delete(f"{BASE}/sources/{row.id}")
    assert response.status_code == 204, response.text
    assert env.secrets.deleted == [f"channel_cred:sentry:{row.id}"]
    env.catalog.clear_references.assert_awaited_once_with("stream_source", str(row.id))


async def test_deleting_an_unknown_source_is_a_404(client, env, graph):
    env.service.delete_source.side_effect = StreamSourceNotFoundError(uuid4())
    assert (await client.delete(f"{BASE}/sources/{uuid4()}")).status_code == 404


async def test_a_stream_triggers_or_forwards_depend_on_is_refused_before_anything_is_released(
    client, env, graph
):
    trigger_id, forward_id, source_stream = uuid4(), uuid4(), uuid4()
    env.service.ensure_deletable.side_effect = StreamInUseError(
        STREAM, [trigger_id], [(forward_id, source_stream)]
    )
    env.service.list_sources.return_value = [_row("github")]
    response = await client.delete(BASE)
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert str(trigger_id) in detail
    assert "delete the trigger" in detail
    assert str(forward_id) in detail
    assert str(source_stream) in detail
    assert env.secrets.deleted == []
    env.service.delete_stream.assert_not_called()


async def test_deleting_a_stream_releases_every_source(client, env, graph):
    webhook, poll = _row("github"), _row("telegram", kind="poll")
    env.service.list_sources.return_value = [webhook, poll]
    response = await client.delete(BASE)
    assert response.status_code == 204, response.text
    assert env.secrets.deleted == [
        f"channel_cred:github:{webhook.id}",
        f"channel_cred:telegram:{poll.id}",
    ]
    env.service.delete_stream.assert_awaited_once()
