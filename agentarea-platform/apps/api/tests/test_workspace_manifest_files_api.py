"""Manifest-backed file API boundaries."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from agentarea_api.api.v1 import agents_tasks, files
from fastapi import HTTPException


async def _response_body(response) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


async def _chunks(*values: bytes):
    for value in values:
        yield value


@pytest.mark.asyncio
async def test_workspace_listing_projects_logical_task_paths_and_hides_storage_keys(
    monkeypatch,
) -> None:
    artifact_service = SimpleNamespace(
        list=AsyncMock(
            return_value=[
                SimpleNamespace(
                    path="projects/p-1/report.txt",
                    size=3,
                    content_type="text/plain",
                    last_modified="now",
                ),
                SimpleNamespace(
                    path="tasks/t-1/current.json",
                    size=1,
                    content_type="application/json",
                    last_modified="now",
                ),
                SimpleNamespace(
                    path="tasks/t-1/objects/abc",
                    size=7,
                    content_type="application/octet-stream",
                    last_modified="now",
                ),
                SimpleNamespace(
                    path="tasks/t-1/sandbox/legacy.txt",
                    size=6,
                    content_type="text/plain",
                    last_modified="now",
                ),
            ]
        )
    )
    workspace_repository = SimpleNamespace(
        list_task_ids=AsyncMock(return_value=["t-1"]),
        list=AsyncMock(
            return_value=[
                SimpleNamespace(path="downloads/image.png", size=7, content_type="image/png")
            ]
        ),
    )
    monkeypatch.setattr(files, "_get_artifact_service", lambda: artifact_service)
    monkeypatch.setattr(files, "_get_workspace_repository", lambda: workspace_repository)
    project_service = SimpleNamespace(list=AsyncMock(return_value=[]))

    result = await files.list_workspace_files(SimpleNamespace(workspace_id="ws-1"), project_service)

    assert [item.path for item in result.files] == [
        "projects/p-1/report.txt",
        "tasks/t-1/workspace/downloads/image.png",
    ]
    workspace_repository.list.assert_awaited_once_with("ws-1", "t-1")
    workspace_repository.list_task_ids.assert_awaited_once_with("ws-1")


@pytest.mark.asyncio
async def test_workspace_download_reads_logical_path_from_manifest(monkeypatch) -> None:
    workspace_repository = SimpleNamespace(
        stream=AsyncMock(return_value=(_chunks(b"canon", b"ical"), "text/plain", 9))
    )
    artifact_service = SimpleNamespace(stream=AsyncMock())
    monkeypatch.setattr(files, "_get_workspace_repository", lambda: workspace_repository)
    monkeypatch.setattr(files, "_get_artifact_service", lambda: artifact_service)

    response = await files.stream_workspace_file(
        "tasks/t-1/workspace/output.txt", SimpleNamespace(workspace_id="ws-1")
    )

    assert await _response_body(response) == b"canonical"
    workspace_repository.stream.assert_awaited_once_with("ws-1", "t-1", "output.txt")
    assert response.headers["content-length"] == "9"
    artifact_service.stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_workspace_download_streams_regular_artifact_without_buffering(monkeypatch) -> None:
    artifact_service = SimpleNamespace(
        stream=AsyncMock(return_value=(_chunks(b"regular", b"-body"), "text/plain", 12))
    )
    monkeypatch.setattr(files, "_get_artifact_service", lambda: artifact_service)

    response = await files.stream_workspace_file(
        "shared/output.txt", SimpleNamespace(workspace_id="ws-1")
    )

    assert await _response_body(response) == b"regular-body"
    artifact_service.stream.assert_awaited_once_with("ws-1", "shared/output.txt")
    assert response.headers["content-length"] == "12"


@pytest.mark.asyncio
async def test_workspace_download_rejects_legacy_task_path(monkeypatch) -> None:
    artifact_service = SimpleNamespace(stream=AsyncMock())
    monkeypatch.setattr(files, "_get_artifact_service", lambda: artifact_service)

    with pytest.raises(HTTPException) as exc_info:
        await files.stream_workspace_file(
            "tasks/t-1/sandbox/legacy.txt", SimpleNamespace(workspace_id="ws-1")
        )

    assert exc_info.value.status_code == 404
    artifact_service.stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_artifact_listing_returns_only_explicit_manager_artifacts(
    monkeypatch,
) -> None:
    task_id = uuid4()
    agent_id = uuid4()
    manager_request = AsyncMock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "art_0123456789abcdef0123456789abcdef",
                        "path": "reports/result.txt",
                        "name": "result.txt",
                        "size": 9,
                        "content_type": "text/plain",
                        "sha256": "a" * 64,
                        "created_at": "2026-07-31T10:00:00Z",
                    }
                ]
            },
        )
    )
    monkeypatch.setattr(agents_tasks, "_sandbox_manager_request", manager_request)

    items = await agents_tasks._list_task_artifact_items(
        agent_id=agent_id, workspace_id="ws-1", task_id=task_id
    )

    assert [(item.id, item.path) for item in items] == [
        ("art_0123456789abcdef0123456789abcdef", "reports/result.txt")
    ]
    assert items[0].download_url.endswith("/artifacts/files/art_0123456789abcdef0123456789abcdef")
    manager_request.assert_awaited_once_with(
        "GET",
        "/sandbox/artifacts",
        params={"workspace_id": "ws-1", "task_id": str(task_id)},
    )


@pytest.mark.asyncio
async def test_task_artifact_download_reads_explicit_artifact_from_manager(
    monkeypatch,
) -> None:
    task_id = uuid4()
    agent_id = uuid4()
    task_service = SimpleNamespace(
        get_task=AsyncMock(return_value=SimpleNamespace(agent_id=agent_id))
    )
    manager_client = SimpleNamespace(aclose=AsyncMock())
    manager_response = httpx.Response(
        200,
        content=b"artifact-body",
        headers={
            "content-type": "text/plain",
            "content-length": "13",
            "content-disposition": 'attachment; filename="result.txt"',
        },
    )
    manager_stream = AsyncMock(return_value=(manager_client, manager_response))
    monkeypatch.setattr(agents_tasks, "_sandbox_manager_stream", manager_stream)
    artifact_id = "art_0123456789abcdef0123456789abcdef"

    response = await agents_tasks.download_task_artifact(
        agent_id,
        task_id,
        artifact_id,
        SimpleNamespace(workspace_id="ws-1"),
        task_service,
    )

    assert await _response_body(response) == b"artifact-body"
    manager_stream.assert_awaited_once_with(
        f"/sandbox/artifacts/{artifact_id}",
        params={"workspace_id": "ws-1", "task_id": str(task_id)},
    )
    assert response.headers["content-length"] == "13"
    manager_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_task_artifact_download_rejects_legacy_task_path(monkeypatch) -> None:
    task_id = uuid4()
    agent_id = uuid4()
    task_service = SimpleNamespace(
        get_task=AsyncMock(return_value=SimpleNamespace(agent_id=agent_id))
    )
    manager_request = AsyncMock()
    monkeypatch.setattr(agents_tasks, "_sandbox_manager_request", manager_request)

    with pytest.raises(HTTPException) as exc_info:
        await agents_tasks.download_task_artifact(
            agent_id,
            task_id,
            f"tasks/{task_id}/sandbox/legacy.txt",
            SimpleNamespace(workspace_id="ws-1"),
            task_service,
        )

    assert exc_info.value.status_code == 404
    manager_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_live_sandbox_file_list_does_not_wake_expired_workspace(monkeypatch) -> None:
    task_id = uuid4()
    agent_id = uuid4()
    task_service = SimpleNamespace(
        get_task=AsyncMock(return_value=SimpleNamespace(agent_id=agent_id))
    )
    manager_request = AsyncMock(
        return_value=httpx.Response(200, json={"paths": ["inputs/a.txt", "reports/out.txt"]})
    )
    monkeypatch.setattr(agents_tasks, "_sandbox_manager_request", manager_request)

    result = await agents_tasks.list_task_sandbox_files(
        agent_id,
        task_id,
        SimpleNamespace(workspace_id="ws-1"),
        "",
        task_service,
    )

    assert [item.path for item in result.items] == ["inputs/a.txt", "reports/out.txt"]
    manager_request.assert_awaited_once_with(
        "GET",
        "/sandbox/files",
        params={
            "workspace_id": "ws-1",
            "task_id": str(task_id),
            "list": "",
            "ensure": "false",
        },
    )


@pytest.mark.asyncio
async def test_live_sandbox_file_read_streams_manager_payload(monkeypatch) -> None:
    task_id = uuid4()
    agent_id = uuid4()
    task_service = SimpleNamespace(
        get_task=AsyncMock(return_value=SimpleNamespace(agent_id=agent_id))
    )
    manager_client = SimpleNamespace(aclose=AsyncMock())
    manager_response = httpx.Response(
        200,
        content=b"hello",
        headers={"content-length": "5"},
    )
    manager_stream = AsyncMock(return_value=(manager_client, manager_response))
    monkeypatch.setattr(agents_tasks, "_sandbox_manager_stream", manager_stream)

    response = await agents_tasks.read_task_sandbox_file(
        agent_id,
        task_id,
        "reports/output.txt",
        SimpleNamespace(workspace_id="ws-1"),
        task_service,
    )

    assert await _response_body(response) == b"hello"
    assert response.media_type == "text/plain"
    assert response.headers["content-length"] == "5"
    manager_stream.assert_awaited_once_with(
        "/sandbox/file-content",
        params={
            "workspace_id": "ws-1",
            "task_id": str(task_id),
            "path": "reports/output.txt",
            "ensure": "false",
        },
    )
    manager_client.aclose.assert_awaited_once()
