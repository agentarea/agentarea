"""Unit-level coverage for ``WebToolset``.

Network and storage are both stubbed:
  - ``httpx.MockTransport`` serves canned responses (text + binary).
  - ``InMemoryStorage`` (the SDK's own in-memory ``StorageClient`` impl)
    catches the binary writes so we can assert on the resulting key
    layout without booting RustFS.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from agentarea_agents_sdk.tools.file_toolset import InMemoryStorage
from agentarea_agents_sdk.tools.web_toolset import WebToolset

_REAL_ASYNC_CLIENT = httpx.AsyncClient  # captured before any monkeypatch


def _patched_client_factory(transport: httpx.MockTransport):
    """Return a context-manager class that mimics ``httpx.AsyncClient``."""

    class _Client:
        def __init__(self, *_, **__) -> None:
            self._client = _REAL_ASYNC_CLIENT(transport=transport)

        async def __aenter__(self):
            return self._client

        async def __aexit__(self, *exc) -> None:
            await self._client.aclose()

    return _Client


@pytest.mark.asyncio
async def test_search_uses_configured_searxng_endpoint(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        assert request.url.params["q"] == "agent benchmarks"
        assert request.url.params["format"] == "json"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "GAIA benchmark",
                        "url": "https://example.test/gaia",
                        "content": "A benchmark for general AI assistants.",
                        "engine": "example",
                    }
                ]
            },
        )

    monkeypatch.setattr(
        "agentarea_agents_sdk.tools.web_toolset.httpx.AsyncClient",
        _patched_client_factory(httpx.MockTransport(handler)),
    )

    payload = json.loads(
        await WebToolset(search_base_url="http://search.test/").search_web("agent benchmarks")
    )

    assert payload["results"] == [
        {
            "title": "GAIA benchmark",
            "url": "https://example.test/gaia",
            "snippet": "A benchmark for general AI assistants.",
            "engine": "example",
        }
    ]


@pytest.mark.asyncio
async def test_search_without_backend_fails_loudly() -> None:
    result = await WebToolset().search_web("agent benchmarks")
    assert result.startswith("Error: web search is not configured")


@pytest.mark.asyncio
async def test_text_response_is_returned_inline(monkeypatch) -> None:
    body = (
        "<html><head><title>T</title></head><body><p>hi</p><a href='/docs'>Docs</a></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})

    monkeypatch.setattr(
        "agentarea_agents_sdk.tools.web_toolset.httpx.AsyncClient",
        _patched_client_factory(httpx.MockTransport(handler)),
    )

    storage = InMemoryStorage()
    tool = WebToolset(storage=storage, workspace_id="ws-1", base_prefix="tasks/t")

    result = await tool.fetch_webpage("https://example.test/page")
    payload = json.loads(result)

    assert payload["kind"] == "text"
    assert payload["status"] == 200
    assert "<p>hi</p>" in payload["text"]
    assert "hi" in payload["extracted_text"]
    assert {"href": "https://example.test/docs", "text": "Docs"} in payload["links"]
    # No artifact written for text responses.
    assert await storage.list("ws-1") == []


@pytest.mark.asyncio
async def test_binary_response_is_persisted_as_artifact(monkeypatch) -> None:
    png = b"\x89PNG\r\n\x1a\n" + bytes(range(64))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=png, headers={"content-type": "image/png"})

    monkeypatch.setattr(
        "agentarea_agents_sdk.tools.web_toolset.httpx.AsyncClient",
        _patched_client_factory(httpx.MockTransport(handler)),
    )

    storage = InMemoryStorage()
    tool = WebToolset(storage=storage, workspace_id="ws-7", base_prefix="tasks/t-9")

    result = await tool.fetch_webpage("https://cdn.example.test/foo.png")
    payload = json.loads(result)

    assert payload["kind"] == "binary"
    assert payload["content_type"] == "image/png"
    assert payload["size"] == len(png)
    expected_path = "tasks/t-9/downloads/foo.png"
    assert payload["artifact_path"] == expected_path

    # The bytes really landed in the storage layer under the workspace.
    data, ct = await storage.get("ws-7", expected_path)
    assert data == png
    assert ct == "image/png"


@pytest.mark.asyncio
async def test_binary_response_is_committed_to_canonical_task_workspace(monkeypatch) -> None:
    png = b"\x89PNG\r\n\x1a\ncanonical"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=png, headers={"content-type": "image/png"})

    monkeypatch.setattr(
        "agentarea_agents_sdk.tools.web_toolset.httpx.AsyncClient",
        _patched_client_factory(httpx.MockTransport(handler)),
    )

    repository = AsyncMock()
    tool = WebToolset(
        workspace_repository=repository,
        workspace_id="ws-7",
        task_id="task-9",
        lease_owner="workflow-9",
    )

    payload = json.loads(await tool.fetch_webpage("https://cdn.example.test/foo.png"))

    assert payload["artifact_path"] == "tasks/task-9/workspace/downloads/foo.png"
    repository.put.assert_awaited_once_with(
        "ws-7",
        "task-9",
        "downloads/foo.png",
        png,
        "image/png",
        owner="workflow-9",
    )


@pytest.mark.asyncio
async def test_canonical_binary_write_requires_task_id(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"png", headers={"content-type": "image/png"})

    monkeypatch.setattr(
        "agentarea_agents_sdk.tools.web_toolset.httpx.AsyncClient",
        _patched_client_factory(httpx.MockTransport(handler)),
    )
    repository = AsyncMock()

    result = await WebToolset(
        workspace_repository=repository,
        workspace_id="ws-7",
    ).fetch_webpage("https://cdn.example.test/foo.png")

    assert result == "Error: task_id is required for canonical workspace writes"
    repository.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_binary_without_storage_returns_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\x00\x01", headers={"content-type": "image/png"})

    monkeypatch.setattr(
        "agentarea_agents_sdk.tools.web_toolset.httpx.AsyncClient",
        _patched_client_factory(httpx.MockTransport(handler)),
    )

    tool = WebToolset(storage=None)
    result = await tool.fetch_webpage("https://cdn.example.test/x.png")
    assert result.startswith("Error: response is binary")


@pytest.mark.asyncio
async def test_non_http_url_is_refused() -> None:
    tool = WebToolset()
    result = await tool.fetch_webpage("file:///etc/passwd")
    assert result.startswith("Error: url must be http(s)")


@pytest.mark.asyncio
async def test_filename_inferred_from_content_type_when_path_has_none(
    monkeypatch,
) -> None:
    pdf = b"%PDF-1.4\n%hello"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=pdf, headers={"content-type": "application/pdf"})

    monkeypatch.setattr(
        "agentarea_agents_sdk.tools.web_toolset.httpx.AsyncClient",
        _patched_client_factory(httpx.MockTransport(handler)),
    )

    storage = InMemoryStorage()
    tool = WebToolset(storage=storage, workspace_id="ws", base_prefix="tasks/t")
    payload = json.loads(await tool.fetch_webpage("https://example.test/report"))

    assert payload["artifact_path"].endswith(".pdf")


@pytest.mark.asyncio
async def test_extract_text_strips_script_and_style() -> None:
    html = (
        "<html><head><style>.x{color:red}</style>"
        "<script>alert(1)</script></head>"
        "<body><h1>Hello</h1><p>World</p></body></html>"
    )
    tool = WebToolset()
    out = await tool.extract_text(html)
    assert "Hello" in out and "World" in out
    assert "alert" not in out and "color:red" not in out


@pytest.mark.asyncio
async def test_extract_text_passthrough_for_non_html() -> None:
    tool = WebToolset()
    assert await tool.extract_text("just plain text") == "just plain text"
    assert await tool.extract_text("") == ""
