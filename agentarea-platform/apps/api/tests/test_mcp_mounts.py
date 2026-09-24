"""Each MCP URL reaches its own server and names its own OAuth resource.

Starlette matches mounts in order, and ``/mcp`` also matches ``/mcp/w/...`` and
``/mcp/clients/...``. Mounted in the wrong order, a pinned-workspace or harness
URL would be served by the bare platform server — spanning workspaces instead of
the one the URL names — and its 401 would send the client to the wrong
RFC 9728 document. The challenge is the observable that tells them apart.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from agentarea_api.main import create_app

API_BASE = "https://api.example.com"
CLIENT_ID = "74dfa41a-1736-4ab1-a470-2e2d4c4e56c8"
_TOOLS_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
_HEADERS = {"Accept": "application/json, text/event-stream"}


async def _challenge(path: str) -> str:
    settings = MagicMock()
    settings.app.API_BASE_URL = API_BASE
    app = create_app()
    with patch("agentarea_common.config.get_settings", return_value=settings):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(path, json=_TOOLS_LIST, headers=_HEADERS)
    assert response.status_code == 401, (path, response.status_code, response.text)
    return response.headers["www-authenticate"]


def _points_at(resource: str | None) -> str:
    location = f"{API_BASE}/.well-known/oauth-protected-resource"
    if resource:
        location = f"{location}/{resource}"
    return f'Bearer resource_metadata="{location}"'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "resource"),
    [
        ("/mcp", None),
        ("/mcp/w/acme", "mcp/w/acme"),
        (f"/mcp/clients/{CLIENT_ID}", f"mcp/clients/{CLIENT_ID}"),
        (f"/client-mcp/{CLIENT_ID}", f"client-mcp/{CLIENT_ID}"),
    ],
)
async def test_each_url_is_served_by_its_own_mount(path, resource):
    assert await _challenge(path) == _points_at(resource)
