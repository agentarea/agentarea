"""Upload planning and archive-instead-of-delete on the workspace files API."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentarea_api.api.v1 import files
from fastapi import HTTPException

WS = SimpleNamespace(workspace_id="ws-1", user_id="user-1")


def _install_service(monkeypatch, **methods):
    defaults = {
        "put": AsyncMock(),
        "archive": AsyncMock(return_value=".trash/20260826T101500.000000Z/notes.md"),
        "copy": AsyncMock(),
        "delete": AsyncMock(),
        "move": AsyncMock(),
        "exists": AsyncMock(return_value=False),
        "list": AsyncMock(return_value=[]),
    }
    service = SimpleNamespace(**{**defaults, **methods})
    monkeypatch.setattr(files, "ArtifactService", lambda **kwargs: service)
    monkeypatch.setattr(files, "_get_artifact_service", lambda: service)
    return service


@pytest.mark.asyncio
async def test_delete_archives_instead_of_destroying(monkeypatch) -> None:
    service = _install_service(monkeypatch, exists=AsyncMock(return_value=True))

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


def _obj(path: str, size: int = 3):
    return SimpleNamespace(path=path, size=size, content_type=None, last_modified=None)


def _exists_only(*paths: str) -> AsyncMock:
    known = set(paths)
    return AsyncMock(side_effect=lambda _ws, path: path in known)


def _list_by_prefix(mapping: dict[str, list]) -> AsyncMock:
    return AsyncMock(side_effect=lambda _ws, prefix="", max_items=1000: mapping.get(prefix, []))


@pytest.mark.asyncio
async def test_move_relocates_a_single_file(monkeypatch) -> None:
    service = _install_service(monkeypatch, exists=_exists_only("wiki/index.md"))

    result = await files.move_workspace_file(
        files.MoveWorkspaceFileRequest(source="wiki/index.md", destination="docs/index.md"), WS
    )

    service.move.assert_awaited_once()
    assert service.move.await_args.args[1:] == ("wiki/index.md", "docs/index.md")
    assert (result.source, result.destination, result.moved) == (
        "wiki/index.md",
        "docs/index.md",
        1,
    )


@pytest.mark.asyncio
async def test_move_relocates_a_folder_keeping_every_suffix(monkeypatch) -> None:
    service = _install_service(
        monkeypatch,
        exists=_exists_only(),
        list=_list_by_prefix(
            {"wiki/": [_obj("wiki/"), _obj("wiki/index.md"), _obj("wiki/api/auth.md")]}
        ),
    )

    result = await files.move_workspace_file(
        files.MoveWorkspaceFileRequest(source="wiki", destination="docs/wiki"), WS
    )

    moved = [call.args[1:] for call in service.move.await_args_list]
    assert moved == [
        ("wiki/", "docs/wiki/"),
        ("wiki/index.md", "docs/wiki/index.md"),
        ("wiki/api/auth.md", "docs/wiki/api/auth.md"),
    ]
    assert result.moved == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "destination"),
    [
        ("tasks/t-1/workspace/out.txt", "wiki/out.txt"),
        ("wiki/index.md", "tasks/t-1/workspace/index.md"),
        ("staging/x/f.txt", "wiki/f.txt"),
        ("wiki/index.md", ".trash/old/index.md"),
        ("wiki/index.md", "../escape.md"),
    ],
)
async def test_move_refuses_reserved_and_escaping_paths(monkeypatch, source, destination) -> None:
    service = _install_service(monkeypatch, exists=_exists_only(source))

    with pytest.raises(HTTPException) as exc:
        await files.move_workspace_file(
            files.MoveWorkspaceFileRequest(source=source, destination=destination), WS
        )

    assert exc.value.status_code == 422
    service.move.assert_not_awaited()


@pytest.mark.asyncio
async def test_move_refuses_a_destination_inside_the_source(monkeypatch) -> None:
    service = _install_service(monkeypatch, exists=_exists_only())

    with pytest.raises(HTTPException) as exc:
        await files.move_workspace_file(
            files.MoveWorkspaceFileRequest(source="wiki", destination="wiki/nested"), WS
        )

    assert exc.value.status_code == 422
    service.move.assert_not_awaited()


@pytest.mark.asyncio
async def test_move_refuses_an_occupied_destination(monkeypatch) -> None:
    service = _install_service(monkeypatch, exists=_exists_only("wiki/index.md", "docs/index.md"))

    with pytest.raises(HTTPException) as exc:
        await files.move_workspace_file(
            files.MoveWorkspaceFileRequest(source="wiki/index.md", destination="docs/index.md"), WS
        )

    assert exc.value.status_code == 409
    service.move.assert_not_awaited()


@pytest.mark.asyncio
async def test_move_reports_a_missing_source(monkeypatch) -> None:
    service = _install_service(monkeypatch, exists=_exists_only())

    with pytest.raises(HTTPException) as exc:
        await files.move_workspace_file(
            files.MoveWorkspaceFileRequest(source="wiki/gone.md", destination="docs/gone.md"), WS
        )

    assert exc.value.status_code == 404
    service.move.assert_not_awaited()


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


SHA = "a" * 64


@pytest.mark.asyncio
async def test_upload_plan_skips_stored_files_and_presigns_the_rest(monkeypatch) -> None:
    digests = {"wiki/index.md": SHA}
    service = _install_service(
        monkeypatch,
        head=AsyncMock(
            side_effect=lambda _ws, path: (
                {"sha256": digests[path]} if path in digests else None
            )
        ),
        authorize_put=AsyncMock(
            return_value=SimpleNamespace(url="https://store/put", headers={"h": "v"}, expires_in=600)
        ),
    )
    body = files.UploadPlanRequest(
        files=[
            files.UploadPlanEntry(path="wiki/index.md", sha256=SHA),
            files.UploadPlanEntry(path="wiki/new.md", sha256=SHA, content_type="text/markdown"),
            files.UploadPlanEntry(path="tasks/t/out.md", sha256=SHA),
        ]
    )

    plan = await files.plan_workspace_uploads(body, WS)

    assert [(u.path, u.status) for u in plan.uploads] == [
        ("wiki/index.md", "unchanged"),
        ("wiki/new.md", "upload"),
        ("tasks/t/out.md", "error"),
    ]
    assert plan.uploads[1].upload_url == "https://store/put"
    service.authorize_put.assert_awaited_once_with(
        "ws-1", "wiki/new.md", sha256_hex=SHA, content_type="text/markdown"
    )


def test_upload_plan_is_bounded() -> None:
    entry = {"path": "a.md", "sha256": SHA}
    with pytest.raises(ValueError):
        files.UploadPlanRequest(files=[])
    with pytest.raises(ValueError):
        files.UploadPlanRequest(files=[entry] * 101)
