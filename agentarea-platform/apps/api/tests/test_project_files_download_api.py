"""Project file download headers.

A project file's bytes and declared content type both come from whoever
uploaded it, so an HTML file must never render inline on our origin — see
issue #483.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.api.v1 import projects
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_project_file_download_sets_nosniff_and_forces_attachment_for_html(
    monkeypatch,
) -> None:
    project_id = uuid4()
    service = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id=project_id)))
    artifact_service = SimpleNamespace(
        get=AsyncMock(return_value=(b"<script>evil()</script>", "text/html"))
    )
    monkeypatch.setattr(projects, "ArtifactService", lambda: artifact_service)

    response = await projects.stream_project_file(
        project_id, "page.html", SimpleNamespace(workspace_id="ws-1"), service
    )

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment;")


@pytest.mark.asyncio
async def test_project_file_download_keeps_attachment_for_plain_text(monkeypatch) -> None:
    project_id = uuid4()
    service = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id=project_id)))
    artifact_service = SimpleNamespace(get=AsyncMock(return_value=(b"hello", "text/plain")))
    monkeypatch.setattr(projects, "ArtifactService", lambda: artifact_service)

    response = await projects.stream_project_file(
        project_id, "notes.txt", SimpleNamespace(workspace_id="ws-1"), service
    )

    assert response.headers["x-content-type-options"] == "nosniff"
    assert 'filename="notes.txt"' in response.headers["content-disposition"]


@pytest.mark.asyncio
async def test_project_file_download_reports_a_missing_project(monkeypatch) -> None:
    service = SimpleNamespace(get=AsyncMock(return_value=None))

    with pytest.raises(HTTPException) as exc_info:
        await projects.stream_project_file(
            uuid4(), "notes.txt", SimpleNamespace(workspace_id="ws-1"), service
        )

    assert exc_info.value.status_code == 404
