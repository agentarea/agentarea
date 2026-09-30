"""A path too long to name an object is a client error, never a 500 from S3."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_agents_sdk.mcp_server.auth import use_mcp_user_context
from agentarea_api.api.v1 import files, projects
from agentarea_api.tools import files_toolset
from agentarea_common.artifacts import ArtifactService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.exceptions.registration import register_error_handlers
from botocore.exceptions import ClientError
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

WORKSPACE_ID = "0b6f5a4e-2c1d-4e8f-9a7b-3c5d6e7f8a9b"
SHA = "a" * 64
LONG_PATHS = [pytest.param("a" * 1100, id="ascii"), pytest.param("é" * 600, id="two-byte")]


class ObjectStore:
    """Answers like S3: a key over 1024 UTF-8 bytes is refused, any other key is absent."""

    @staticmethod
    def _check(key: str, operation: str) -> None:
        if len(key.encode()) > 1024:
            raise ClientError(
                {"Error": {"Code": "KeyTooLongError", "Message": "Your key is too long"}},
                operation,
            )

    def head_object(self, *, Key, **_):
        self._check(Key, "HeadObject")
        raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

    def get_object(self, *, Key, **_):
        self._check(Key, "GetObject")
        raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")

    def copy_object(self, *, Key, CopySource, **_):
        self._check(CopySource["Key"], "CopyObject")
        self._check(Key, "CopyObject")
        raise ClientError({"Error": {"Code": "NoSuchKey"}}, "CopyObject")

    def delete_object(self, *, Key, **_):
        self._check(Key, "DeleteObject")

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        return "https://store.example/put"


def _artifact_service() -> ArtifactService:
    store = ObjectStore()
    return ArtifactService(client=store, public_client=store, bucket="artifacts")


def _client(monkeypatch) -> AsyncClient:
    service = _artifact_service()
    monkeypatch.setattr(files, "ArtifactService", lambda **kwargs: service)
    monkeypatch.setattr(files, "_get_artifact_service", lambda: service)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(files.router, prefix="/v1/workspaces/{workspace}")
    app.dependency_overrides[get_user_context] = lambda: UserContext(
        user_id="user-a", workspace_id=WORKSPACE_ID
    )
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("path", LONG_PATHS)
@pytest.mark.parametrize(
    ("method", "route"),
    [
        ("GET", "/files/{path}"),
        ("GET", "/files/download/{path}"),
        ("DELETE", "/files/{path}"),
        ("POST", "/files/restore/.trash/20261001T120000.000000Z/{path}"),
    ],
)
async def test_reading_or_removing_a_too_long_path_is_not_found(
    monkeypatch, method, route, path
) -> None:
    async with _client(monkeypatch) as client:
        response = await client.request(method, "/v1/workspaces/acme" + route.format(path=path))

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("path", LONG_PATHS)
@pytest.mark.parametrize(
    ("route", "body"),
    [
        ("/files/directories", lambda path: {"path": path}),
        ("/files/move", lambda path: {"source": "notes.md", "destination": path}),
        (
            "/files/upload-url",
            lambda path: {"filename": path, "content_type": "text/plain", "sha256": SHA, "size": 1},
        ),
    ],
)
async def test_writing_a_too_long_path_is_refused(monkeypatch, route, body, path) -> None:
    async with _client(monkeypatch) as client:
        response = await client.post("/v1/workspaces/acme" + route, json=body(path))

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("path", LONG_PATHS)
async def test_upload_plan_reports_a_too_long_path_on_its_own_entry(monkeypatch, path) -> None:
    async with _client(monkeypatch) as client:
        response = await client.post(
            "/v1/workspaces/acme/files/upload-urls",
            json={"files": [{"path": path, "sha256": SHA}]},
        )

    assert response.status_code == 200, response.text
    assert response.json()["uploads"][0]["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", LONG_PATHS)
@pytest.mark.parametrize(
    "handler",
    [projects.stream_project_file, projects.download_project_file, projects.delete_project_file],
)
async def test_a_too_long_project_file_path_is_not_found(monkeypatch, handler, path) -> None:
    service = _artifact_service()
    monkeypatch.setattr(projects, "ArtifactService", lambda **kwargs: service)
    project_id = uuid4()
    project_service = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id=project_id)))
    user_context = UserContext(user_id="user-a", workspace_id=WORKSPACE_ID)

    with pytest.raises(HTTPException) as exc:
        await handler(project_id, path, user_context, project_service)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("path", LONG_PATHS)
@pytest.mark.parametrize("tool", ["get_url", "delete"])
async def test_the_mcp_files_tool_reports_a_too_long_path_as_not_found(
    monkeypatch, tool, path
) -> None:
    service = _artifact_service()
    user_context = UserContext(user_id="user-a", workspace_id=WORKSPACE_ID)

    @asynccontextmanager
    async def context():
        yield (None, user_context, None, None, None)

    monkeypatch.setattr(files_toolset, "ArtifactService", lambda **kwargs: service)
    monkeypatch.setattr(files_toolset, "platform_context", context)
    monkeypatch.setattr(files_toolset, "platform_read_context", context)

    with use_mcp_user_context(user_context):
        result = json.loads(await getattr(files_toolset.FilesToolset(), tool)(path=path))

    assert result["error"] == "File not found"
