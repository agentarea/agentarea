"""Upload placement and archive-instead-of-delete on the workspace files API."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentarea_api.api.v1 import files
from fastapi import HTTPException

WS = SimpleNamespace(workspace_id="ws-1", user_id="user-1")


def _upload(filename: str = "notes.md", content: bytes = b"hi"):
    return SimpleNamespace(
        filename=filename,
        content_type="text/markdown",
        read=AsyncMock(return_value=content),
    )


def _install_service(monkeypatch, **methods):
    defaults = {
        "put": AsyncMock(),
        "archive": AsyncMock(return_value=".trash/20260826T101500.000000Z/notes.md"),
        "copy": AsyncMock(),
        "delete": AsyncMock(),
        "exists": AsyncMock(return_value=True),
    }
    service = SimpleNamespace(**{**defaults, **methods})
    monkeypatch.setattr(files, "ArtifactService", lambda **kwargs: service)
    monkeypatch.setattr(files, "_get_artifact_service", lambda: service)
    return service


@pytest.mark.asyncio
async def test_upload_keeps_the_requested_directory_structure(monkeypatch) -> None:
    service = _install_service(monkeypatch)

    await files.upload_file(_upload(), WS, purpose="workspace", path="wiki/api/auth.md")

    assert service.put.await_args.args[1] == "wiki/api/auth.md"


@pytest.mark.asyncio
async def test_upload_without_a_path_lands_at_the_root(monkeypatch) -> None:
    service = _install_service(monkeypatch)

    await files.upload_file(_upload("report.md"), WS, purpose="workspace", path="")

    assert service.put.await_args.args[1] == "report.md"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_path",
    ["../escape.md", "/absolute.md", "wiki/../../etc/passwd", "wiki//double.md"],
)
async def test_upload_rejects_paths_that_escape_the_workspace(monkeypatch, bad_path) -> None:
    service = _install_service(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        await files.upload_file(_upload(), WS, purpose="workspace", path=bad_path)

    assert exc.value.status_code == 422
    service.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_refuses_to_write_into_reserved_prefixes(monkeypatch) -> None:
    service = _install_service(monkeypatch)

    for reserved in ("tasks/t-1/out.txt", "staging/x/f.txt", ".trash/old/f.txt"):
        with pytest.raises(HTTPException) as exc:
            await files.upload_file(_upload(), WS, purpose="workspace", path=reserved)
        assert exc.value.status_code == 422

    service.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_archives_instead_of_destroying(monkeypatch) -> None:
    service = _install_service(monkeypatch)

    await files.delete_workspace_file("wiki/index.md", WS)

    service.archive.assert_awaited_once()
    assert service.archive.await_args.args[1] == "wiki/index.md"
    service.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_rejects_task_owned_paths(monkeypatch) -> None:
    service = _install_service(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        await files.delete_workspace_file("tasks/t-1/workspace/out.txt", WS)

    assert exc.value.status_code == 400
    service.archive.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_reports_a_missing_file(monkeypatch) -> None:
    service = _install_service(monkeypatch, exists=AsyncMock(return_value=False))

    with pytest.raises(HTTPException) as exc:
        await files.delete_workspace_file("wiki/gone.md", WS)

    assert exc.value.status_code == 404
    service.archive.assert_not_awaited()


@pytest.mark.asyncio
async def test_archived_files_are_hidden_from_the_listing(monkeypatch) -> None:
    artifact_service = SimpleNamespace(
        list=AsyncMock(
            return_value=[
                SimpleNamespace(
                    path="wiki/index.md", size=3, content_type="text/markdown", last_modified="now"
                ),
                SimpleNamespace(
                    path=".trash/20260826T101500.000000Z/wiki/old.md",
                    size=3,
                    content_type="text/markdown",
                    last_modified="now",
                ),
            ]
        )
    )
    monkeypatch.setattr(files, "_get_artifact_service", lambda: artifact_service)
    monkeypatch.setattr(
        files,
        "_get_workspace_repository",
        lambda: SimpleNamespace(list_task_ids=AsyncMock(return_value=[]), list=AsyncMock()),
    )
    project_service = SimpleNamespace(list=AsyncMock(return_value=[]))

    result = await files.list_workspace_files(WS, project_service)

    assert [f.path for f in result.files] == ["wiki/index.md"]


@pytest.mark.asyncio
async def test_restore_puts_an_archived_file_back(monkeypatch) -> None:
    service = _install_service(monkeypatch)
    trash_path = ".trash/20260826T101500.000000Z/wiki/index.md"

    result = await files.restore_workspace_file(trash_path, WS)

    service.copy.assert_awaited_once()
    assert service.copy.await_args.args[1:] == (trash_path, "wiki/index.md")
    assert result.path == "wiki/index.md"


@pytest.mark.asyncio
async def test_restore_rejects_a_path_outside_the_trash(monkeypatch) -> None:
    service = _install_service(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        await files.restore_workspace_file("wiki/index.md", WS)

    assert exc.value.status_code == 400
    service.copy.assert_not_awaited()
