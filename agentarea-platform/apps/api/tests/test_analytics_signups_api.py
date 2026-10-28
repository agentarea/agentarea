"""POST /internal/analytics/signups: Kratos reports each sign-up and the channel it came from."""

from unittest.mock import AsyncMock

import pytest
from agentarea_api.api.internal import analytics_signups
from agentarea_api.main import app
from agentarea_common.analytics import Installation, pseudonymize
from agentarea_common.config import get_settings
from agentarea_common.config.database import get_db_session
from httpx import ASGITransport, AsyncClient

KEY = "k" * 48
INSTALL_ID = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"  # pragma: allowlist secret
BODY = {
    "identity_id": "identity-1",
    "created_at": "2026-10-28T09:30:00.123456Z",
    "request_url": (
        "https://auth.agentarea.ru/self-service/registration/browser"
        "?aa_ref=www.google.com&aa_lh=agentarea.ai&aa_lp=%2Fskills%2Fa%2F"
    ),
}


class FakeSender:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def enqueue(self, event: dict) -> None:
        self.events.append(event)


@pytest.fixture
def settings(monkeypatch):
    def _set(*, key: str | None, enabled: bool = True) -> None:
        if key is None:
            monkeypatch.delenv("AGENTAREA_ANALYTICS_SIGNUP_HOOK_KEY", raising=False)
        else:
            monkeypatch.setenv("AGENTAREA_ANALYTICS_SIGNUP_HOOK_KEY", key)
        monkeypatch.setenv("AGENTAREA_ANALYTICS_ENABLED", "true" if enabled else "false")
        get_settings.cache_clear()

    yield _set
    get_settings.cache_clear()


@pytest.fixture
def stored(monkeypatch):
    rows: dict[str, dict] = {}

    async def _upsert(_session, *, identity_id, created_at, method, attribution):
        if identity_id in rows:
            return False
        rows[identity_id] = {"created_at": created_at, "method": method, "attribution": attribution}
        return True

    async def _installation(_session):
        return Installation(id=INSTALL_ID)

    async def _session():
        yield AsyncMock()

    monkeypatch.setattr(analytics_signups, "upsert_signup_attribution", _upsert)
    monkeypatch.setattr(analytics_signups, "get_or_create_installation", _installation)
    app.dependency_overrides[get_db_session] = _session
    yield rows
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture
def sender(monkeypatch):
    fake = FakeSender()
    monkeypatch.setattr(analytics_signups, "current_sender", lambda: fake)
    return fake


async def _post(body: dict = BODY, *, key: str | None = KEY, method: str = "password"):
    headers = {"Authorization": key} if key is not None else {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(
            "/internal/analytics/signups", params={"method": method}, json=body, headers=headers
        )


async def test_without_a_configured_key_the_endpoint_does_not_exist(settings, stored, sender):
    settings(key=None)

    response = await _post()

    assert response.status_code == 404
    assert stored == {}
    assert sender.events == []


@pytest.mark.parametrize("presented", ["wrong", "", None, f"Bearer {KEY}"])
async def test_a_wrong_or_missing_key_is_refused(settings, stored, sender, presented):
    settings(key=KEY)

    response = await _post(key=presented)

    assert response.status_code == 401
    assert stored == {}
    assert sender.events == []


async def test_a_sign_up_is_stored_and_sent_once(settings, stored, sender):
    settings(key=KEY)

    response = await _post()

    assert response.status_code == 204
    row = stored["identity-1"]
    assert row["method"] == "password"
    assert row["attribution"].channel == "search"
    assert row["created_at"].tzinfo is None
    assert row["created_at"].isoformat() == "2026-10-28T09:30:00.123456"
    assert sender.events == [
        {
            "event": "sign_up",
            "user_id": pseudonymize(INSTALL_ID, "identity-1"),
            "properties": {
                "channel": "search",
                "method": "password",
                "landing_host": "agentarea.ai",
                "landing_path": "/skills/*",
                "referrer_host": "www.google.com",
                "utm_source": None,
                "utm_medium": None,
                "utm_campaign": None,
            },
        }
    ]


async def test_a_replayed_hook_sends_nothing_more(settings, stored, sender):
    settings(key=KEY)
    await _post()

    response = await _post(method="oidc")

    assert response.status_code == 204
    assert stored["identity-1"]["method"] == "password"
    assert len(sender.events) == 1


async def test_an_unknown_method_is_stored_as_null(settings, stored, sender):
    settings(key=KEY)

    response = await _post(method="webauthn")

    assert response.status_code == 204
    assert stored["identity-1"]["method"] is None
    assert sender.events[0]["properties"]["method"] is None


async def test_without_a_request_url_the_sign_up_is_direct(settings, stored, sender):
    settings(key=KEY)

    response = await _post({**BODY, "request_url": None})

    assert response.status_code == 204
    assert stored["identity-1"]["attribution"].channel == "direct"


async def test_with_analytics_off_the_row_is_stored_and_nothing_is_sent(settings, stored, sender):
    settings(key=KEY, enabled=False)

    response = await _post()

    assert response.status_code == 204
    assert "identity-1" in stored
    assert sender.events == []


async def test_the_route_is_left_out_of_the_public_api_schema():
    assert "/internal/analytics/signups" not in app.openapi()["paths"]
