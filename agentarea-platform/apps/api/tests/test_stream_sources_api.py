"""A webhook source added to a stream directly: credentials by reference, never echoed."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_api.api.deps.services import get_secret_catalog_service, get_secret_manager
from agentarea_api.api.v1._trigger_creation import get_channel_webhook_service
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
from agentarea_streams.domain import SourceFedByTriggerError, StreamSourceNotFoundError
from httpx import ASGITransport, AsyncClient

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
STREAM = uuid4()
BASE = f"/v1/workspaces/acme/streams/{STREAM}"


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


def _row(webhook_type: str, *, trigger_id=None, validation_rules=None):
    source_id = uuid4()
    return SimpleNamespace(
        id=source_id,
        kind="webhook",
        webhook_id="wh-abc",
        webhook_type=webhook_type,
        allowed_methods=["POST"],
        validation_rules=validation_rules or {},
        credential_key=trigger_id or source_id,
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
    service.add_webhook_source.side_effect = lambda **kw: _row(
        kw["webhook_type"], validation_rules=kw["validation_rules"]
    )
    secrets = _Secrets({"gh-hook": "from-catalog", "bot": "123:abc"})
    catalog = AsyncMock()
    hooks = AsyncMock()
    hooks.webhook_url = lambda wid: f"https://api.example/webhooks/{wid}"
    hooks.register.return_value = True
    overrides = {
        get_stream_service: lambda: service,
        get_secret_manager: lambda: secrets,
        get_secret_catalog_service: lambda: catalog,
        get_channel_webhook_service: lambda: hooks,
        get_user_context: lambda: UserContext(user_id="u", workspace_id="ws"),
        get_db_session: lambda: AsyncMock(),
    }
    app.dependency_overrides.update(overrides)
    monkeypatch.setattr(
        "agentarea_api.api.v1.streams.public_webhook_url",
        lambda wid: f"https://api.example/webhooks/{wid}",
    )
    yield SimpleNamespace(service=service, secrets=secrets, catalog=catalog, hooks=hooks)
    for dep in overrides:
        app.dependency_overrides.pop(dep, None)


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def _stored(env, webhook_type: str, source_id: str) -> dict:
    return json.loads(env.secrets.values[f"channel_cred:{webhook_type}:{source_id}"])


async def test_the_source_types_come_from_the_api(client, env, graph):
    response = await client.get("/v1/workspaces/acme/streams/source-types")
    assert response.status_code == 200, response.text
    types = {t["webhook_type"]: t for t in response.json()}
    assert {"generic", "github", "sentry", "yookassa", "stripe", "telegram", "slack", "email"} <= (
        set(types)
    )
    assert [f["key"] for f in types["sentry"]["credentials"]] == ["client_secret"]
    assert [f["key"] for f in types["yookassa"]["config"]] == ["shop_id"]
    assert types["yookassa"]["verification"] == "api_lookup"
    assert "payment.succeeded" in types["yookassa"]["events"]


async def test_a_typed_secret_is_stored_under_the_source_and_never_returned(client, env, graph):
    response = await client.post(
        f"{BASE}/sources",
        json={"webhook_type": "sentry", "credentials": {"client_secret": "s3cret"}},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["webhook_url"] == "https://api.example/webhooks/wh-abc"
    assert body["trigger_id"] is None
    assert body["signing_secret"] is None
    assert "s3cret" not in response.text
    assert _stored(env, "sentry", body["id"]) == {"client_secret": "s3cret"}
    kwargs = env.service.add_webhook_source.await_args.kwargs
    assert kwargs["validation_rules"] == {}
    assert "s3cret" not in json.dumps(kwargs, default=str)


async def test_a_picked_workspace_secret_is_held_by_name_and_recorded_as_used(client, env, graph):
    secret_id = uuid4()
    env.catalog.get_for_use.return_value = SimpleNamespace(id=secret_id, secret_name="gh-hook")
    response = await client.post(
        f"{BASE}/sources",
        json={
            "webhook_type": "github",
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
        json={"webhook_type": "github", "credentials": {"webhook_secret": {"secret_id": str(uuid4())}}},
    )
    assert response.status_code == 403
    env.service.add_webhook_source.assert_not_called()


@pytest.mark.parametrize(
    ("payload", "says"),
    [
        ({"webhook_type": "sentry"}, "needs client_secret"),
        ({"webhook_type": "github", "credentials": {"webhook_secret": ""}}, "needs webhook_secret"),
        ({"webhook_type": "yookassa", "credentials": {"secret_key": "k"}}, "needs shop_id"),
        (
            {"webhook_type": "yookassa", "config": {"shop_id": "1"}},
            "needs secret_key",
        ),
        (
            {"webhook_type": "github", "credentials": {"webhook_secret": "x", "token": "y"}},
            "no credential token",
        ),
        (
            {"webhook_type": "github", "credentials": {"webhook_secret": "x"}, "config": {"a": "b"}},
            "no setting a",
        ),
        ({"webhook_type": "gitlab"}, "Unknown source type"),
    ],
)
async def test_a_source_its_verifier_cannot_run_for_is_refused(client, env, graph, payload, says):
    response = await client.post(f"{BASE}/sources", json=payload)
    assert response.status_code == 422, response.text
    assert says in response.json()["detail"]
    env.service.add_webhook_source.assert_not_called()
    assert env.secrets.values == {"gh-hook": "from-catalog", "bot": "123:abc"}


@pytest.mark.parametrize("webhook_type", ["generic", "email"])
async def test_a_source_without_its_optional_secret_is_issued_one_shown_once(
    client, env, graph, webhook_type
):
    response = await client.post(f"{BASE}/sources", json={"webhook_type": webhook_type})
    assert response.status_code == 201, response.text
    body = response.json()
    issued = body["signing_secret"]
    assert issued and len(issued) >= 32
    assert _stored(env, webhook_type, body["id"]) == {"signing_secret": issued}
    assert body["signature_scheme"] == {
        "header": "X-Webhook-Signature",
        "algorithm": "sha256",
        "prefix": "",
    }
    listed = await client.get(f"{BASE}/sources")
    assert issued not in listed.text


async def test_a_generic_source_reports_the_scheme_its_settings_choose(client, env, graph):
    env.service.list_sources.return_value = [
        _row(
            "generic",
            validation_rules={"signature_header": "X-Sig", "signature_prefix": "sha256="},
        ),
        _row("sentry"),
    ]
    generic, sentry = (await client.get(f"{BASE}/sources")).json()
    assert generic["signature_scheme"] == {
        "header": "X-Sig",
        "algorithm": "sha256",
        "prefix": "sha256=",
    }
    assert sentry["signature_scheme"] is None


async def test_a_secret_given_for_an_optional_field_is_kept_and_never_returned(client, env, graph):
    response = await client.post(
        f"{BASE}/sources",
        json={"webhook_type": "email", "credentials": {"signing_secret": "mine"}},
    )
    assert response.status_code == 201, response.text
    assert response.json()["signing_secret"] is None
    assert "mine" not in response.text
    assert _stored(env, "email", response.json()["id"]) == {"signing_secret": "mine"}


async def test_yookassa_settings_are_kept_on_the_source_for_the_verifier(client, env, graph):
    response = await client.post(
        f"{BASE}/sources",
        json={
            "webhook_type": "yookassa",
            "credentials": {"secret_key": "live_x"},
            "config": {"shop_id": "506751"},
        },
    )
    assert response.status_code == 201, response.text
    assert env.service.add_webhook_source.await_args.kwargs["validation_rules"] == {
        "shop_id": "506751"
    }
    assert _stored(env, "yookassa", response.json()["id"]) == {"secret_key": "live_x"}


async def test_a_telegram_source_registers_its_webhook_with_a_fresh_token(client, env, graph):
    secret_id = uuid4()
    env.catalog.get_for_use.return_value = SimpleNamespace(id=secret_id, secret_name="bot")
    response = await client.post(
        f"{BASE}/sources",
        json={"webhook_type": "telegram", "credentials": {"bot_token": {"secret_id": str(secret_id)}}},
    )
    assert response.status_code == 201, response.text
    stored = _stored(env, "telegram", response.json()["id"])
    assert stored["bot_token"] == {"secret_name": "bot"}
    register = env.hooks.register.await_args.kwargs
    assert register["credentials"] == {"bot_token": "123:abc"}
    assert register["secret_token"] == stored["secret_token"]


async def test_a_telegram_source_the_provider_refuses_is_not_saved(client, env, graph):
    env.hooks.register.return_value = False
    response = await client.post(
        f"{BASE}/sources",
        json={"webhook_type": "telegram", "credentials": {"bot_token": "123:abc"}},
    )
    assert response.status_code == 502
    assert not any(k.startswith("channel_cred:") for k in env.secrets.values)


async def test_deleting_a_source_drops_its_credentials_and_references(client, env, graph):
    row = _row("sentry")
    env.service.delete_source.return_value = row
    env.secrets.values[f"channel_cred:sentry:{row.id}"] = "{}"
    response = await client.delete(f"{BASE}/sources/{row.id}")
    assert response.status_code == 204, response.text
    assert env.secrets.deleted == [f"channel_cred:sentry:{row.id}"]
    env.catalog.clear_references.assert_awaited_once_with("stream_source", str(row.id))


async def test_a_source_a_live_trigger_owns_cannot_be_deleted(client, env, graph):
    trigger_id = uuid4()
    env.service.delete_source.side_effect = SourceFedByTriggerError("Source x", [trigger_id])
    response = await client.delete(f"{BASE}/sources/{uuid4()}")
    assert response.status_code == 409
    assert str(trigger_id) in response.json()["detail"]
    assert env.secrets.deleted == []


async def test_deleting_an_unknown_source_is_a_404(client, env, graph):
    env.service.delete_source.side_effect = StreamSourceNotFoundError(uuid4())
    assert (await client.delete(f"{BASE}/sources/{uuid4()}")).status_code == 404


async def test_a_stream_a_live_trigger_feeds_cannot_be_deleted(client, env, graph):
    trigger_id = uuid4()
    env.service.triggers_feeding.return_value = {uuid4(): trigger_id}
    response = await client.delete(BASE)
    assert response.status_code == 409
    assert str(trigger_id) in response.json()["detail"]
    env.service.delete_stream.assert_not_called()


async def test_deleting_a_stream_releases_its_standalone_sources(client, env, graph):
    standalone, owned = _row("github"), _row("github", trigger_id=uuid4())
    env.service.triggers_feeding.return_value = {}
    env.service.list_sources.return_value = [standalone, owned]
    response = await client.delete(BASE)
    assert response.status_code == 204, response.text
    assert env.secrets.deleted == [f"channel_cred:github:{standalone.id}"]
    env.service.delete_stream.assert_awaited_once()


async def test_a_trigger_owned_source_is_listed_with_its_trigger(client, env, graph):
    trigger_id = uuid4()
    env.service.list_sources.return_value = [_row("github", trigger_id=trigger_id)]
    response = await client.get(f"{BASE}/sources")
    assert response.json()[0]["trigger_id"] == str(trigger_id)
