"""Tests for the request body size limit middleware."""

import pytest
from agentarea_api.api.body_size_middleware import BodySizeLimitMiddleware
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(max_bytes: int) -> TestClient:
    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_bytes)

    @app.post("/echo")
    async def echo() -> dict:
        return {"ok": True}

    return TestClient(app)


def test_body_under_limit_passes():
    client = _client(max_bytes=1000)
    resp = client.post("/echo", content=b"x" * 100)
    assert resp.status_code == 200


def test_body_over_limit_rejected_with_413():
    client = _client(max_bytes=1000)
    resp = client.post("/echo", content=b"x" * 2000)
    assert resp.status_code == 413
    assert "too large" in resp.json()["detail"].lower()


@pytest.mark.parametrize("size", [999, 1000])
def test_body_at_or_below_limit_passes(size):
    client = _client(max_bytes=1000)
    resp = client.post("/echo", content=b"x" * size)
    assert resp.status_code == 200
