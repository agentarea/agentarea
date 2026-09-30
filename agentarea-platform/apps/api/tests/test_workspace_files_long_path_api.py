"""A path too long to name an object is a client error, never a 500 from S3."""

from __future__ import annotations

import pytest
from agentarea_api.api.v1 import files
from agentarea_common.artifacts import ArtifactService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.exceptions.registration import register_error_handlers
from botocore.exceptions import ClientError
from fastapi import FastAPI
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


def _client(monkeypatch) -> AsyncClient:
    store = ObjectStore()
    service = ArtifactService(client=store, public_client=store, bucket="artifacts")
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
