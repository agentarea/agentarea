"""Tests for the request body size limit middleware.

The limit used to be read off ``Content-Length`` alone, so a body sent with
``Transfer-Encoding: chunked`` -- which carries no length -- went straight past
it and was buffered in full by the handler (#712). The body is now also
counted as it streams in.
"""

from collections.abc import Iterator

import pytest
from agentarea_api.api.body_size_middleware import BodySizeLimitMiddleware
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket
from fastapi.testclient import TestClient

LIMIT = 1000


def _client(max_bytes: int = LIMIT) -> TestClient:
    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_bytes)

    @app.post("/echo")
    async def echo() -> dict:
        return {"ok": True}

    @app.post("/read")
    async def read(request: Request) -> dict:
        return {"size": len(await request.body())}

    @app.post("/upload")
    async def upload(file: UploadFile = File(...)) -> dict:
        return {"size": len(await file.read())}

    @app.post("/swallow")
    async def swallow(request: Request) -> dict:
        # A handler that turns every read failure into its own 400: the limit
        # still decides the answer.
        try:
            body = await request.body()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="bad body") from exc
        return {"size": len(body)}

    return TestClient(app)


def _chunked(total: int, chunk: int = 100) -> Iterator[bytes]:
    """A body with no Content-Length: httpx sends it Transfer-Encoding: chunked."""
    sent = 0
    while sent < total:
        size = min(chunk, total - sent)
        sent += size
        yield b"x" * size


def _multipart(payload: bytes) -> tuple[bytes, str]:
    boundary = "----limit-test"
    head = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="pad.bin"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    return head + payload + f"\r\n--{boundary}--\r\n".encode(), (
        f"multipart/form-data; boundary={boundary}"
    )


def test_body_under_limit_passes():
    client = _client()
    resp = client.post("/echo", content=b"x" * 100)
    assert resp.status_code == 200


def test_body_over_limit_rejected_with_413():
    client = _client()
    resp = client.post("/echo", content=b"x" * 2000)
    assert resp.status_code == 413
    assert "too large" in resp.json()["detail"].lower()


@pytest.mark.parametrize("size", [999, 1000])
def test_body_at_or_below_limit_passes(size):
    client = _client()
    resp = client.post("/echo", content=b"x" * size)
    assert resp.status_code == 200


@pytest.mark.parametrize("path", ["/read", "/swallow"])
def test_a_chunked_body_over_the_limit_is_413(path):
    resp = _client().post(path, content=_chunked(LIMIT * 5))

    assert resp.request.headers.get("transfer-encoding") == "chunked"
    assert "content-length" not in resp.request.headers
    assert resp.status_code == 413, resp.text
    assert resp.json() == {"detail": "Request body too large"}


def test_a_chunked_upload_over_the_limit_is_413():
    body, content_type = _multipart(b"x" * (LIMIT * 5))

    def stream() -> Iterator[bytes]:
        for start in range(0, len(body), 100):
            yield body[start : start + 100]

    resp = _client().post("/upload", content=stream(), headers={"Content-Type": content_type})

    assert resp.request.headers.get("transfer-encoding") == "chunked"
    assert resp.status_code == 413, resp.text


@pytest.mark.parametrize("size", [0, 999, 1000])
def test_a_chunked_body_within_the_limit_is_read_whole(size):
    resp = _client().post("/read", content=_chunked(size))

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"size": size}


def test_a_body_longer_than_its_declared_length_is_counted_too():
    """A Content-Length under the limit does not unlock a bigger body."""
    resp = _client().post(
        "/read", content=_chunked(LIMIT * 5), headers={"Content-Length": str(LIMIT // 2)}
    )

    assert resp.status_code == 413, resp.text


def test_non_http_scopes_pass_through():
    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=1)

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_text("hello there")
        await websocket.close()

    with TestClient(app).websocket_connect("/ws") as websocket:
        assert websocket.receive_text() == "hello there"
