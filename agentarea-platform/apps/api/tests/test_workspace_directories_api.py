"""Persistent workspace folders and their file-path boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.api.v1 import files, projects
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _app(monkeypatch, stored_paths=(), projects=()):
    objects = {
        path: SimpleNamespace(
            path=path, size=0, content_type="application/octet-stream", last_modified=None
        )
        for path in stored_paths
    }

    async def put(workspace_id, path, data, content_type=None):
        objects[path] = SimpleNamespace(
            path=path, size=len(data), content_type=content_type, last_modified=None
        )

    async def list_objects(workspace_id, prefix="", max_items=1000):
        return [obj for path, obj in objects.items() if path.startswith(prefix)][:max_items]

    service = SimpleNamespace(
        exists=AsyncMock(side_effect=lambda workspace_id, path: path in objects),
        list=AsyncMock(side_effect=list_objects),
        put=AsyncMock(side_effect=put),
    )
    monkeypatch.setattr(files, "ArtifactService", lambda **kwargs: service)
    monkeypatch.setattr(files, "_get_artifact_service", lambda: service)
    monkeypatch.setattr(
        files,
        "_get_workspace_repository",
        lambda: SimpleNamespace(list_task_ids=AsyncMock(return_value=[])),
    )
    app = FastAPI()
    app.include_router(files.router, prefix="/v1")
    app.dependency_overrides[get_user_context] = lambda: UserContext(
        user_id="user-a", workspace_id="workspace-a"
    )
    app.dependency_overrides[files.get_project_service] = lambda: SimpleNamespace(
        list=AsyncMock(return_value=[SimpleNamespace(id=project) for project in projects])
    )
    return app, service


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["docs/Планы", "docs/Планы/"])
async def test_create_folder_persists_a_workspace_scoped_marker_and_lists_it(monkeypatch, path):
    app, service = _app(monkeypatch, projects=["p-1"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/v1/files/directories", json={"path": path})
        listing = await client.get("/v1/files")

    assert created.status_code == 201, created.text
    assert created.json() == {"path": "docs/Планы/"}
    service.put.assert_awaited_once_with(
        "workspace-a", "docs/Планы/", b"", content_type="application/x-directory"
    )
    assert listing.json() == {"files": [], "directories": ["docs/Планы/", "projects/p-1/"]}
    assert all(call.args[0] == "workspace-a" for call in service.list.await_args_list)
    assert all(call.args[0] == "workspace-a" for call in service.exists.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "",
        "/",
        "/absolute",
        "../escape",
        "docs/../escape",
        "docs//nested",
        "docs//",
        "docs/./nested",
        "docs\\nested",
        "docs/\nnew",
        "tasks",
        "tasks/new",
        "staging",
        "staging/new",
        ".trash",
        ".trash/new",
    ],
)
async def test_create_folder_rejects_noncanonical_and_reserved_paths(monkeypatch, path):
    app, service = _app(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/files/directories", json={"path": path})

    assert response.status_code == 422, response.text
    service.put.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored_paths", "path"),
    [
        (["docs"], "docs"),
        (["docs"], "docs/nested"),
        (["docs/nested"], "docs/nested/child"),
        (["docs/"], "docs"),
        (["docs/report.md"], "docs"),
    ],
)
async def test_create_folder_rejects_existing_files_and_folders(monkeypatch, stored_paths, path):
    app, service = _app(monkeypatch, stored_paths)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/files/directories", json={"path": path})

    assert response.status_code == 409, response.text
    service.put.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["projects", "projects/p-1"])
async def test_create_folder_respects_empty_project_directories(monkeypatch, path):
    app, service = _app(monkeypatch, projects=["p-1"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/files/directories", json={"path": path})

    assert response.status_code == 409, response.text
    service.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_nested_folder_under_an_existing_directory(monkeypatch):
    app, _ = _app(monkeypatch, stored_paths=["docs/"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/files/directories", json={"path": "docs/nested"})

    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_listing_hides_reserved_markers_and_deduplicates_project_folders(monkeypatch):
    app, _ = _app(
        monkeypatch,
        stored_paths=["docs/", "docs/report.md", "projects/p-1/", "staging/", ".trash/", "tasks/"],
        projects=["p-1"],
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/files")

    assert response.status_code == 200
    assert response.json()["directories"] == ["docs/", "projects/p-1/"]
    assert [item["path"] for item in response.json()["files"]] == ["docs/report.md"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored_paths", "path"),
    [(["docs/"], "docs"), (["docs/report.md"], "docs"), (["docs"], "docs/report.md")],
)
async def test_upload_rejects_file_folder_collisions(monkeypatch, stored_paths, path):
    app, service = _app(monkeypatch, stored_paths)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/files", data={"path": path}, files={"file": ("report.md", b"report", "text/plain")}
        )

    assert response.status_code == 409, response.text
    service.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_inside_folder_keeps_the_folder_and_allows_file_replacement(monkeypatch):
    app, service = _app(monkeypatch, stored_paths=["docs/", "docs/report.md"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/files",
            data={"path": "docs/report.md"},
            files={"file": ("report.md", b"updated", "text/plain")},
        )

    assert response.status_code == 204, response.text
    service.put.assert_awaited_once_with(
        "workspace-a", "docs/report.md", b"updated", content_type="text/plain"
    )


@pytest.mark.asyncio
async def test_project_listing_does_not_expose_directory_markers_as_files(monkeypatch):
    project_id = uuid4()
    prefix = f"projects/{project_id}/"
    artifact_service = SimpleNamespace(
        list=AsyncMock(
            return_value=[
                SimpleNamespace(path=f"{prefix}docs/", size=0, last_modified=None),
                SimpleNamespace(path=f"{prefix}docs/report.md", size=6, last_modified=None),
            ]
        )
    )
    monkeypatch.setattr(projects, "ArtifactService", lambda: artifact_service)
    response = await projects.list_project_files(
        project_id,
        UserContext(user_id="user-a", workspace_id="workspace-a"),
        SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id=project_id))),
    )

    assert [item.path for item in response.files] == ["docs/report.md"]
    artifact_service.list.assert_awaited_once_with("workspace-a", prefix=prefix)
