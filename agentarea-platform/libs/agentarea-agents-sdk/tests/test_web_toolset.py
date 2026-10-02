"""Unit-level coverage for ``WebToolset``.

The network is stubbed with ``httpx.MockTransport``: search through a patched
``httpx.AsyncClient``, fetch through the client factory the toolset is given.
"""

from __future__ import annotations

import json

import httpx
import pytest

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


def _fetching(handler) -> WebToolset:
    """A toolset whose fetch client is served by ``handler``."""
    transport = httpx.MockTransport(handler)
    return WebToolset(
        http_client_factory=lambda **kw: _REAL_ASYNC_CLIENT(transport=transport, **kw)
    )


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
async def test_html_page_is_returned_inline_with_text_and_links() -> None:
    body = (
        "<html><head><title>T</title><style>.hidden{color:red}</style></head>"
        "<body><script>alert(1)</script><p>смета</p><a href='/docs'>Docs</a></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=body.encode(), headers={"content-type": "text/html; charset=utf-8"}
        )

    result = await _fetching(handler).fetch_webpage("https://example.test/page")
    payload = json.loads(result)

    assert payload["status"] == 200
    assert "<p>смета</p>" in payload["text"]
    assert "смета" in payload["extracted_text"]
    assert "alert" not in payload["extracted_text"]
    assert "color:red" not in payload["extracted_text"]
    assert {"href": "https://example.test/docs", "text": "Docs"} in payload["links"]
    # Links stay readable in the conversation, where the next fetch is checked.
    assert "смета" in result


@pytest.mark.asyncio
async def test_redirect_is_followed_and_final_url_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://example.test/new"})
        return httpx.Response(200, text="moved here", headers={"content-type": "text/plain"})

    payload = json.loads(await _fetching(handler).fetch_webpage("https://example.test/old"))

    assert payload["url"] == "https://example.test/new"
    assert payload["text"] == "moved here"


@pytest.mark.asyncio
async def test_binary_content_is_refused_not_stored() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})

    result = await _fetching(handler).fetch_webpage("https://example.test/report.pdf")

    assert result.startswith("Error:")
    assert "application/pdf" in result
    assert "sandbox shell" in result


@pytest.mark.asyncio
async def test_oversized_page_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"a" * (5 * 1024 * 1024 + 1), headers={"content-type": "text/plain"}
        )

    result = await _fetching(handler).fetch_webpage("https://example.test/huge")

    assert result.startswith("Error:")
    assert "larger than" in result


@pytest.mark.asyncio
async def test_transport_refusal_is_reported_as_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusing request to non-public address", request=request)

    result = await _fetching(handler).fetch_webpage("https://internal.test/")

    assert result.startswith("Error fetching https://internal.test/")


@pytest.mark.asyncio
async def test_non_http_url_is_refused() -> None:
    result = await _fetching(lambda r: httpx.Response(200)).fetch_webpage("file:///etc/passwd")
    assert result.startswith("Error: url must be http(s)")


@pytest.mark.asyncio
async def test_fetch_without_client_fails_closed() -> None:
    result = await WebToolset().fetch_webpage("https://example.test/")
    assert result.startswith("Error: web fetching is not configured")


def test_web_toolset_exposes_only_search_and_fetch() -> None:
    definitions = WebToolset().get_tool_definitions()
    assert {definition.name for definition in definitions} == {
        "web_search_web",
        "web_fetch_webpage",
    }
