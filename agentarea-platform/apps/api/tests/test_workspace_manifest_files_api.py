"""Manifest-backed file API boundaries."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

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
        )
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
async def test_task_artifact_listing_returns_manifest_entries_only(
    monkeypatch,
) -> None:
    task_id = uuid4()
    agent_id = uuid4()
    workspace_repository = SimpleNamespace(
        list=AsyncMock(
            return_value=[SimpleNamespace(path="result.txt", size=9, content_type="text/plain")]
        )
    )
    legacy_artifact_service = SimpleNamespace(
        list=AsyncMock(
            return_value=[
                SimpleNamespace(
                    path=f"tasks/{task_id}/sandbox/legacy.txt",
                    size=6,
                    content_type="text/plain",
                    last_modified="now",
                )
            ]
        )
    )
    import agentarea_common.artifacts as artifacts

    monkeypatch.setattr(artifacts, "WorkspaceRepository", lambda: workspace_repository)
    monkeypatch.setattr(artifacts, "ArtifactService", lambda: legacy_artifact_service)

    items = await agents_tasks._list_task_artifact_items(
        agent_id=agent_id, workspace_id="ws-1", task_id=task_id
    )

    assert [item.path for item in items] == [f"tasks/{task_id}/workspace/result.txt"]
    legacy_artifact_service.list.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_artifact_download_reads_manifest_not_raw_workspace_key(
    monkeypatch,
) -> None:
    task_id = uuid4()
    agent_id = uuid4()
    task_service = SimpleNamespace(
        get_task=AsyncMock(return_value=SimpleNamespace(agent_id=agent_id))
    )
    workspace_repository = SimpleNamespace(
        stream=AsyncMock(
            return_value=(_chunks(b"manifest-", b"body"), "text/plain", 13)
        )
    )
    import agentarea_common.artifacts as artifacts

    monkeypatch.setattr(artifacts, "WorkspaceRepository", lambda: workspace_repository)

    response = await agents_tasks.download_task_artifact(
        agent_id,
        task_id,
        f"tasks/{task_id}/workspace/result.txt",
        SimpleNamespace(workspace_id="ws-1"),
        task_service,
    )

    assert await _response_body(response) == b"manifest-body"
    workspace_repository.stream.assert_awaited_once_with(
        "ws-1", str(task_id), "result.txt"
    )
    assert response.headers["content-length"] == "13"


@pytest.mark.asyncio
async def test_task_artifact_download_rejects_legacy_task_path(monkeypatch) -> None:
    task_id = uuid4()
    agent_id = uuid4()
    task_service = SimpleNamespace(
        get_task=AsyncMock(return_value=SimpleNamespace(agent_id=agent_id))
    )
    workspace_repository = SimpleNamespace(stream=AsyncMock())
    import agentarea_common.artifacts as artifacts

    monkeypatch.setattr(artifacts, "WorkspaceRepository", lambda: workspace_repository)

    with pytest.raises(HTTPException) as exc_info:
        await agents_tasks.download_task_artifact(
            agent_id,
            task_id,
            f"tasks/{task_id}/sandbox/legacy.txt",
            SimpleNamespace(workspace_id="ws-1"),
            task_service,
        )

    assert exc_info.value.status_code == 404
    workspace_repository.stream.assert_not_awaited()
