"""An OAuth flow whose workspace was deleted mid-flight lands on the frontend, not a 500.

Both callbacks send the browser back into the workspace the flow started in.
When that workspace no longer exists there is nowhere to send it; the user
gets the frontend root with the reason as data, and the event is logged.
"""

import urllib.parse
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentarea_api.api.v1 import connection_oauth, mcp_oauth_connect

FRONTEND = SimpleNamespace(app=SimpleNamespace(FRONTEND_BASE_URL="https://app.agentarea.ai"))
STATE = {
    "connection_id": "d50241d7-eafe-4011-8479-b40f7a2aab3c",
    "instance_id": "d50241d7-eafe-4011-8479-b40f7a2aab3c",
    "auth_config_id": "7f0e0a52-2a55-4f8a-9d0c-3d9f1c6b2e11",
    "workspace_id": "ws-deleted",
    "user_id": "alice",
    "code_verifier": "v",
    "return_to": "",
    "as_metadata": {
        "issuer": "https://as.example",
        "authorization_endpoint": "https://as.example/authorize",
        "token_endpoint": "https://as.example/token",
        "resource": "",
    },
}


def _gone(workspace_id: str) -> str:
    raise LookupError(f"Workspace {workspace_id} does not exist")


def _assert_landed_on_root(response) -> None:
    location = urllib.parse.urlparse(response.headers["location"])
    assert response.status_code == 302
    assert (location.scheme, location.netloc, location.path) == (
        "https",
        "app.agentarea.ai",
        "/",
    )
    assert urllib.parse.parse_qs(location.query) == {
        "oauth": ["error"],
        "reason": ["workspace_gone"],
    }


@pytest.mark.asyncio
async def test_connection_callback_for_a_deleted_workspace(monkeypatch):
    monkeypatch.setattr(connection_oauth, "get_settings", lambda: FRONTEND)
    monkeypatch.setattr(connection_oauth, "_pop_state", AsyncMock(return_value=dict(STATE)))
    monkeypatch.setattr(connection_oauth, "workspace_slug_for", AsyncMock(side_effect=_gone))

    response = await connection_oauth.oauth_callback(
        db_session=None, code="code", state="s", error=None, error_description=None
    )

    _assert_landed_on_root(response)


@pytest.mark.asyncio
async def test_mcp_callback_for_a_deleted_workspace(monkeypatch):
    monkeypatch.setattr(mcp_oauth_connect, "get_settings", lambda: FRONTEND)
    monkeypatch.setattr(mcp_oauth_connect, "_pop_state", AsyncMock(return_value=dict(STATE)))
    monkeypatch.setattr(mcp_oauth_connect, "workspace_slug_for", AsyncMock(side_effect=_gone))

    response = await mcp_oauth_connect.oauth_callback(
        db_session=None, code="code", state="s", error=None, error_description=None
    )

    _assert_landed_on_root(response)
