from types import SimpleNamespace

import httpx
import pytest
from agentarea_api.api.v1.sandboxes import list_sandboxes
from fastapi import HTTPException
from pydantic import SecretStr


class _AsyncClient:
    def __init__(self, response: httpx.Response, capture: dict):
        self._response = response
        self._capture = capture

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url: str, **kwargs):
        self._capture["url"] = url
        self._capture.update(kwargs)
        return self._response


def _settings(secret: str | None):
    return SimpleNamespace(
        mcp=SimpleNamespace(
            MCP_MANAGER_URL="http://mcp-manager",
            SANDBOX_INSPECTION_AUTH_SECRET=SecretStr(secret) if secret else None,
        )
    )


@pytest.mark.asyncio
async def test_list_sandboxes_uses_authenticated_workspace(monkeypatch):
    capture: dict = {}
    response = httpx.Response(
        200,
        json={
            "items": [
                {
                    "id": "sbx-1",
                    "provider": "opensandbox",
                    "workspace_id": "workspace-a",
                    "task_id": "task-1",
                    "state": "running",
                    "created_at": "2026-07-30T10:00:00Z",
                    "expires_at": "2026-07-30T12:00:00Z",
                    "resources": {"cpu": "500m", "memory": "512Mi"},
                    "isolation": "gvisor",
                }
            ],
            "total": 1,
        },
    )
    monkeypatch.setattr(
        "agentarea_api.api.v1.sandboxes.get_settings",
        lambda: _settings("inspection-secret"),
    )
    monkeypatch.setattr(
        "agentarea_api.api.v1.sandboxes.httpx.AsyncClient",
        lambda **_kwargs: _AsyncClient(response, capture),
    )

    result = await list_sandboxes(SimpleNamespace(user_id="user-a", workspace_id="workspace-a"))

    assert result.total == 1
    assert capture["url"] == "http://mcp-manager/sandbox/sessions"
    assert capture["params"] == {"workspace_id": "workspace-a"}
    assert capture["headers"]["Authorization"] == "Bearer inspection-secret"
    assert "workspace_id" not in result.model_dump()["items"][0]


@pytest.mark.asyncio
async def test_list_sandboxes_fails_closed_without_inspection_secret(monkeypatch):
    monkeypatch.setattr(
        "agentarea_api.api.v1.sandboxes.get_settings",
        lambda: _settings(None),
    )

    with pytest.raises(HTTPException) as exc:
        await list_sandboxes(SimpleNamespace(user_id="u", workspace_id="w"))

    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_list_sandboxes_rejects_cross_workspace_upstream_item(monkeypatch):
    response = httpx.Response(
        200,
        json={
            "items": [
                {
                    "id": "sbx-other",
                    "provider": "opensandbox",
                    "workspace_id": "workspace-b",
                    "task_id": "task-b",
                    "state": "running",
                    "created_at": "2026-07-30T10:00:00Z",
                    "expires_at": None,
                    "resources": {"cpu": "500m", "memory": "512Mi"},
                    "isolation": "gvisor",
                }
            ],
            "total": 1,
        },
    )
    monkeypatch.setattr(
        "agentarea_api.api.v1.sandboxes.get_settings",
        lambda: _settings("inspection-secret"),
    )
    monkeypatch.setattr(
        "agentarea_api.api.v1.sandboxes.httpx.AsyncClient",
        lambda **_kwargs: _AsyncClient(response, {}),
    )

    with pytest.raises(HTTPException) as exc:
        await list_sandboxes(SimpleNamespace(user_id="user-a", workspace_id="workspace-a"))

    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_list_sandboxes_maps_manager_failure_to_unavailable(monkeypatch):
    monkeypatch.setattr(
        "agentarea_api.api.v1.sandboxes.get_settings",
        lambda: _settings("inspection-secret"),
    )
    monkeypatch.setattr(
        "agentarea_api.api.v1.sandboxes.httpx.AsyncClient",
        lambda **_kwargs: _AsyncClient(httpx.Response(503, text="not ready"), {}),
    )

    with pytest.raises(HTTPException) as exc:
        await list_sandboxes(SimpleNamespace(user_id="u", workspace_id="w"))

    assert exc.value.status_code == 503
