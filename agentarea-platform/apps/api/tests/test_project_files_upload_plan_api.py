"""Project upload plans stay inside the project's prefix."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.api.v1 import projects
from agentarea_api.api.v1.files import UploadPlanEntry, UploadPlanRequest
from fastapi import HTTPException

SHA = "a" * 64
WS = SimpleNamespace(workspace_id="ws-1", user_id="user-1")


def _install_service(monkeypatch, stored: dict[str, str] | None = None):
    digests = stored or {}
    service = SimpleNamespace(
        head=AsyncMock(
            side_effect=lambda _ws, path: {"sha256": digests[path]} if path in digests else None
        ),
        exists=AsyncMock(return_value=False),
        list=AsyncMock(return_value=[]),
        authorize_put=AsyncMock(
            return_value=SimpleNamespace(url="https://store/put", headers={"h": "v"}, expires_in=600)
        ),
    )
    monkeypatch.setattr(projects, "ArtifactService", lambda **kwargs: service)
    return service


def _project_service(project_id):
    return SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id=project_id)))


def _body(*paths: str) -> UploadPlanRequest:
    return UploadPlanRequest(files=[UploadPlanEntry(path=p, sha256=SHA) for p in paths])


@pytest.mark.asyncio
async def test_plan_reports_an_unknown_project(monkeypatch) -> None:
    service = _install_service(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        await projects.plan_project_uploads(
            uuid4(), _body("notes.md"), WS, SimpleNamespace(get=AsyncMock(return_value=None))
        )

    assert exc.value.status_code == 404
    service.authorize_put.assert_not_awaited()


@pytest.mark.asyncio
async def test_plan_maps_relative_paths_under_the_project_prefix(monkeypatch) -> None:
    project_id = uuid4()
    prefix = f"projects/{project_id}/"
    service = _install_service(monkeypatch, stored={f"{prefix}docs/old.md": SHA})

    plan = await projects.plan_project_uploads(
        project_id, _body("docs/old.md", "docs/new.md"), WS, _project_service(project_id)
    )

    assert [(u.path, u.status) for u in plan.uploads] == [
        ("docs/old.md", "unchanged"),
        ("docs/new.md", "upload"),
    ]
    assert plan.uploads[1].upload_url == "https://store/put"
    service.authorize_put.assert_awaited_once_with(
        "ws-1", f"{prefix}docs/new.md", sha256_hex=SHA, content_type=None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_path", ["../escape.md", "/absolute.md", "docs/../../x.md", ""])
async def test_plan_refuses_paths_that_leave_the_project_per_entry(monkeypatch, bad_path) -> None:
    project_id = uuid4()
    service = _install_service(monkeypatch)

    plan = await projects.plan_project_uploads(
        project_id, _body(bad_path, "ok.md"), WS, _project_service(project_id)
    )

    assert [(u.path, u.status) for u in plan.uploads] == [(bad_path, "error"), ("ok.md", "upload")]
    assert plan.uploads[0].upload_url is None
    service.authorize_put.assert_awaited_once()
    assert service.authorize_put.await_args.args[1] == f"projects/{project_id}/ok.md"
