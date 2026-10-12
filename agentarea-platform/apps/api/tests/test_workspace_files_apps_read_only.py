"""``apps/`` is listed in the workspace but written only by its MCP apps.

An app keeps its state under ``apps/{instance_id}/`` through the manager's
conditional writes; every manual write surface here refuses that prefix while
the listing and downloads keep showing it.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentarea_agents_sdk.mcp_server.auth import use_mcp_user_context
from agentarea_api.api.v1 import files
from agentarea_api.tools import files_toolset
from agentarea_api.tools.files_toolset import FilesToolset
from agentarea_common.auth.context import UserContext
from fastapi import HTTPException

WS = SimpleNamespace(workspace_id="ws-1", user_id="user-1")
APP_FILE = "apps/0b6f7c1e-0000-4000-8000-000000000001/app.sqlite"
SHA = "a" * 64


def _service(monkeypatch, **methods):
    defaults = {
        "put": AsyncMock(),
        "archive": AsyncMock(),
        "restore": AsyncMock(),
        "delete": AsyncMock(),
        "move": AsyncMock(),
        "exists": AsyncMock(return_value=True),
        "list": AsyncMock(return_value=[]),
        "head": AsyncMock(return_value=None),
        "authorize_put": AsyncMock(),
    }
    service = SimpleNamespace(**{**defaults, **methods})
    monkeypatch.setattr(files, "ArtifactService", lambda **kwargs: service)
    monkeypatch.setattr(files, "_get_artifact_service", lambda: service)
    return service


def _untouched(service) -> None:
    for name in ("put", "archive", "restore", "delete", "move", "authorize_put"):
        getattr(service, name).assert_not_awaited()


@pytest.mark.asyncio
async def test_app_files_stay_in_the_listing(monkeypatch) -> None:
    _service(
        monkeypatch,
        list=AsyncMock(
            return_value=[
                SimpleNamespace(path=APP_FILE, size=4096, content_type=None, last_modified=None)
            ]
        ),
    )

    result = await files.list_workspace_files(WS, SimpleNamespace(list=AsyncMock(return_value=[])))

    assert [f.path for f in result.files] == [APP_FILE]


@pytest.mark.asyncio
async def test_deleting_an_app_file_is_refused(monkeypatch) -> None:
    service = _service(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        await files.delete_workspace_file(APP_FILE, WS)

    assert exc.value.status_code == 403
    assert "read-only" in exc.value.detail
    _untouched(service)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "destination"),
    [
        (APP_FILE, "wiki/app.sqlite"),
        ("wiki/notes.md", "apps/notes.md"),
        ("apps", "archive/apps"),
    ],
)
async def test_moving_into_or_out_of_apps_is_refused(monkeypatch, source, destination) -> None:
    service = _service(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        await files.move_workspace_file(
            files.MoveWorkspaceFileRequest(source=source, destination=destination), WS
        )

    assert exc.value.status_code == 403
    _untouched(service)


@pytest.mark.asyncio
async def test_creating_a_folder_under_apps_is_refused(monkeypatch) -> None:
    service = _service(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        await files.create_workspace_directory(
            files.CreateWorkspaceDirectoryRequest(path="apps/new/"),
            WS,
            SimpleNamespace(list=AsyncMock(return_value=[])),
        )

    assert exc.value.status_code == 403
    _untouched(service)


@pytest.mark.asyncio
async def test_restoring_an_archived_app_file_is_refused(monkeypatch) -> None:
    service = _service(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        await files.restore_workspace_file(f".trash/20261005T101500.000000Z/{APP_FILE}", WS)

    assert exc.value.status_code == 403
    _untouched(service)


@pytest.mark.asyncio
async def test_an_upload_plan_reports_app_paths_as_errors(monkeypatch) -> None:
    service = _service(monkeypatch)

    plan = await files.plan_workspace_uploads(
        files.UploadPlanRequest(files=[files.UploadPlanEntry(path=APP_FILE, sha256=SHA)]), WS
    )

    assert [(u.path, u.status) for u in plan.uploads] == [(APP_FILE, "error")]
    assert "read-only" in (plan.uploads[0].error or "")
    _untouched(service)


@pytest.fixture
def mcp_service(monkeypatch):
    service = SimpleNamespace(
        exists=AsyncMock(return_value=True),
        list=AsyncMock(return_value=[]),
        head=AsyncMock(return_value=None),
        delete=AsyncMock(),
        authorize_put=AsyncMock(),
    )

    @asynccontextmanager
    async def fake_context():
        yield (None, UserContext(user_id="user-1", workspace_id="ws-1"), None, None, None)

    monkeypatch.setattr(files_toolset, "ArtifactService", lambda **kwargs: service)
    monkeypatch.setattr(files_toolset, "platform_context", fake_context)
    with use_mcp_user_context(UserContext(user_id="user-1", workspace_id="ws-1")):
        yield service


@pytest.mark.asyncio
async def test_the_mcp_delete_tool_refuses_app_files(mcp_service) -> None:
    result = json.loads(await FilesToolset().delete(path=APP_FILE))

    assert result["deleted"] is False
    assert "read-only" in result["error"]
    mcp_service.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_mcp_upload_tool_refuses_app_paths(mcp_service) -> None:
    result = json.loads(await FilesToolset().upload_urls(files=[{"path": APP_FILE, "sha256": SHA}]))

    assert result["uploads"][0]["status"] == "error"
    mcp_service.authorize_put.assert_not_awaited()
