"""End-to-end artifact flows against the real S3-compatible store (RustFS).

These are the load-bearing tests for ``agentarea_common.artifacts``: they
drive the exact shapes the platform uses — store bytes the agent produced,
store bytes pulled from an external HTTP source, list by prefix (the
"folder" view), read back via presigned URL, and verify cross-workspace
isolation is unbreakable.

Requires the dev stack (RustFS on :9000) and the usual AWS_* env:
    AWS_ENDPOINT_URL  http://localhost:9000
    AWS_ACCESS_KEY_ID rustfsadmin
    AWS_SECRET_ACCESS_KEY rustfsadmin
    ARTIFACTS_BUCKET_NAME artifacts
"""

from __future__ import annotations

import asyncio
import os
import uuid

import httpx
import pytest

from agentarea_common.artifacts import ArtifactService

pytestmark = [pytest.mark.integration]


def _default_env() -> None:
    """Populate AWS_* defaults so a plain ``uv run pytest`` works locally."""
    os.environ.setdefault("AWS_ENDPOINT_URL", "http://localhost:9000")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "rustfsadmin")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "rustfsadmin")
    os.environ.setdefault("AWS_REGION", "us-east-1")
    os.environ.setdefault("ARTIFACTS_BUCKET_NAME", "artifacts")


_default_env()


@pytest.fixture
def ws() -> str:
    return f"test-{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def svc(ws: str):
    service = ArtifactService()
    try:
        yield service
    finally:
        for obj in await service.list(ws):
            await service.delete(ws, obj.path)


async def test_put_and_get_text_roundtrip(svc: ArtifactService, ws: str) -> None:
    ref = await svc.put(ws, "tasks/t1/note.txt", b"hello world", "text/plain")
    assert ref.size == 11
    assert ref.content_type == "text/plain"

    data, ct = await svc.get(ws, "tasks/t1/note.txt")
    assert data == b"hello world"
    assert ct is not None and ct.startswith("text/plain")


async def test_put_and_get_binary_blob(svc: ArtifactService, ws: str) -> None:
    """Agent/tool produced an image — store raw bytes, read them back unmodified."""
    png = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4  # ~1 KiB binary payload
    ref = await svc.put(ws, "tasks/t1/diagram.png", png, "image/png")
    assert ref.size == len(png)
    assert ref.content_type == "image/png"

    data, ct = await svc.get(ws, "tasks/t1/diagram.png")
    assert data == png
    assert ct == "image/png"


async def test_list_returns_objects_under_prefix(svc: ArtifactService, ws: str) -> None:
    """The 'folder' view: one workspace can have many task scopes + shared dir."""
    await asyncio.gather(
        svc.put(ws, "tasks/alpha/a.txt", b"a", "text/plain"),
        svc.put(ws, "tasks/alpha/b.txt", b"b", "text/plain"),
        svc.put(ws, "tasks/beta/c.txt", b"c", "text/plain"),
        svc.put(ws, "shared/doc.md", b"d", "text/markdown"),
    )

    alpha = await svc.list(ws, prefix="tasks/alpha/")
    assert sorted(o.path for o in alpha) == ["tasks/alpha/a.txt", "tasks/alpha/b.txt"]

    all_tasks = await svc.list(ws, prefix="tasks/")
    assert sorted(o.path for o in all_tasks) == [
        "tasks/alpha/a.txt",
        "tasks/alpha/b.txt",
        "tasks/beta/c.txt",
    ]

    shared = await svc.list(ws, prefix="shared/")
    assert [o.path for o in shared] == ["shared/doc.md"]


async def test_workspace_isolation_is_enforced(svc: ArtifactService) -> None:
    """No workspace may see another workspace's objects — the only barrier."""
    ws_a = f"a-{uuid.uuid4().hex[:8]}"
    ws_b = f"b-{uuid.uuid4().hex[:8]}"
    try:
        await svc.put(ws_a, "secret.txt", b"classified", "text/plain")

        b_list = await svc.list(ws_b)
        assert b_list == []

        assert not await svc.exists(ws_b, "secret.txt")
        with pytest.raises(FileNotFoundError):
            await svc.get(ws_b, "secret.txt")

        assert await svc.exists(ws_a, "secret.txt")
    finally:
        for w in (ws_a, ws_b):
            for obj in await svc.list(w):
                await svc.delete(w, obj.path)


async def test_presigned_url_serves_the_bytes(svc: ArtifactService, ws: str) -> None:
    """A presigned GET is what the frontend and external consumers actually use."""
    payload = b"presigned-" + uuid.uuid4().hex.encode()
    await svc.put(ws, "tasks/t1/file.bin", payload, "application/octet-stream")

    url = await svc.presigned_url(ws, "tasks/t1/file.bin", expires_in=60)
    async with httpx.AsyncClient(timeout=10.0) as http:
        resp = await http.get(url)
    resp.raise_for_status()
    assert resp.content == payload


async def test_path_traversal_is_refused(svc: ArtifactService, ws: str) -> None:
    """``..`` must never escape the workspace prefix — defence in depth."""
    with pytest.raises(ValueError, match=r"\.\."):
        await svc.put(ws, "../evil.txt", b"nope")


async def test_missing_workspace_id_is_refused(svc: ArtifactService) -> None:
    """Callers must pass a workspace_id on every operation."""
    with pytest.raises(ValueError, match="workspace_id"):
        await svc.put("", "file.txt", b"no")


async def test_download_external_then_store_as_artifact(
    svc: ArtifactService, ws: str
) -> None:
    """Pull bytes from the public internet, persist them under the task scope.

    This is exactly the flow for any tool that returns remote content (web
    fetch, image gen, document download) — the worker fetches, stores the
    raw bytes under ``tasks/{task_id}/`` and the agent references the
    artifact later.

    Skipped if the external host is unreachable; local RustFS is always up.
    """
    url = "https://httpbin.org/bytes/64"
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            resp = await http.get(url)
            resp.raise_for_status()
    except (httpx.HTTPError, httpx.TransportError):
        pytest.skip("httpbin.org unreachable")

    blob = resp.content
    assert len(blob) == 64
    content_type = resp.headers.get("content-type") or "application/octet-stream"

    ref = await svc.put(ws, "tasks/t1/fetched.bin", blob, content_type)
    assert ref.size == 64

    readback, ct = await svc.get(ws, "tasks/t1/fetched.bin")
    assert readback == blob
    assert ct is not None


async def test_api_upload_then_readback(svc: ArtifactService, ws: str) -> None:
    """The platform receives bytes over HTTP, stores them, returns a ref.

    Simulates a tool that returns a generated image: the worker gets the
    bytes + mime type, stores under the task scope, and later operations
    can read back via the same key (or via presigned URL).
    """
    fake_jpeg = b"\xff\xd8\xff\xe0" + b"JFIF\x00" + b"\x00" * 500
    ref = await svc.put(ws, "tasks/t1/photo.jpg", fake_jpeg, "image/jpeg")
    assert ref.content_type == "image/jpeg"
    assert ref.size == len(fake_jpeg)

    data, ct = await svc.get(ws, "tasks/t1/photo.jpg")
    assert data == fake_jpeg
    assert ct == "image/jpeg"

    listed = await svc.list(ws, prefix="tasks/t1/")
    assert any(o.path == "tasks/t1/photo.jpg" and o.size == len(fake_jpeg) for o in listed)


async def test_delete_removes_object(svc: ArtifactService, ws: str) -> None:
    await svc.put(ws, "tasks/t1/ephemeral.txt", b"bye", "text/plain")
    assert await svc.exists(ws, "tasks/t1/ephemeral.txt")

    await svc.delete(ws, "tasks/t1/ephemeral.txt")
    assert not await svc.exists(ws, "tasks/t1/ephemeral.txt")

    with pytest.raises(FileNotFoundError):
        await svc.get(ws, "tasks/t1/ephemeral.txt")


async def test_overwrite_replaces_bytes(svc: ArtifactService, ws: str) -> None:
    """Put-with-same-key replaces the object; last write wins."""
    await svc.put(ws, "tasks/t1/log.txt", b"v1", "text/plain")
    await svc.put(ws, "tasks/t1/log.txt", b"v2-longer-payload", "text/plain")

    data, _ = await svc.get(ws, "tasks/t1/log.txt")
    assert data == b"v2-longer-payload"
