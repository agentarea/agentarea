"""GET /v1/analytics tells the webapp whether, and as which installation, to report."""

from unittest.mock import MagicMock

import pytest
from agentarea_api.api.v1 import analytics
from agentarea_common.analytics import COLLECTOR_KEY, COLLECTOR_URL, Installation
from agentarea_common.auth.dependencies import get_principal
from agentarea_common.config import get_app_settings, get_settings
from fastapi.routing import APIRoute


@pytest.fixture
def analytics_enabled(monkeypatch):
    def _set(enabled: bool) -> None:
        monkeypatch.setenv("AGENTAREA_ANALYTICS_ENABLED", "true" if enabled else "false")
        get_settings.cache_clear()

    yield _set
    get_settings.cache_clear()


async def test_on_it_names_the_installation_and_the_collector(analytics_enabled, monkeypatch):
    analytics_enabled(True)
    session = MagicMock()

    async def _installation(passed):
        assert passed is session
        return Installation(id="0f1e2d3c4b5a69788796a5b4c3d2e1f0")  # pragma: allowlist secret

    monkeypatch.setattr(analytics, "get_or_create_installation", _installation)

    response = await analytics.get_analytics(session)

    assert response.model_dump() == {
        "enabled": True,
        "install_id": "0f1e2d3c4b5a69788796a5b4c3d2e1f0",
        "collector_url": COLLECTOR_URL,
        "collector_key": COLLECTOR_KEY,
        "edition": get_app_settings().EDITION,
    }


async def test_off_it_names_nothing_and_touches_no_table(analytics_enabled, monkeypatch):
    analytics_enabled(False)

    async def _installation(_session):
        raise AssertionError("analytics off must not create the installation row")

    monkeypatch.setattr(analytics, "get_or_create_installation", _installation)

    response = await analytics.get_analytics(MagicMock())

    assert response.model_dump() == {
        "enabled": False,
        "install_id": None,
        "collector_url": None,
        "collector_key": None,
        "edition": None,
    }


def test_route_is_served_behind_authentication():
    from agentarea_api.main import app

    route = next(r for r in app.routes if isinstance(r, APIRoute) and r.path == "/v1/analytics")
    stack, calls = list(route.dependant.dependencies), set()
    while stack:
        dep = stack.pop()
        calls.add(dep.call)
        stack.extend(dep.dependencies)

    assert route.methods == {"GET"}
    assert get_principal in calls
