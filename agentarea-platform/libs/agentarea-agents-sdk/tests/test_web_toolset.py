"""Unit-level coverage for ``WebToolset``.

The network is stubbed with ``httpx.MockTransport``: search through a patched
``httpx.AsyncClient``, fetch through the client factory the toolset is given.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import httpx2
import pytest

from agentarea_agents_sdk.tools.web_toolset import WebToolset
from agentarea_agents_sdk.tools.code_tools_loader import create_code_tool_instance
from agentarea_agents_sdk.tools.decorator_tool import ToolsetAdapter
from agentarea_agents_sdk.tools.tool_executor import ToolExecutor

_REAL_ASYNC_CLIENT = httpx.AsyncClient  # captured before any monkeypatch
_REAL_MCP_CLIENT = httpx2.AsyncClient


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


@pytest.fixture
def parallel_transport(monkeypatch):
    """Serve real MCP client exchanges; keep the toolset/dispatcher unmocked."""
    calls = []
    tool_result = {
        "content": [],
        "structuredContent": {
            "results": [
                {
                    "url": "https://example.test/смета",
                    "title": "Research",
                    "excerpts": ["Evidence"],
                },
                {"url": "javascript:alert(1)", "title": "Invalid", "excerpts": []},
                {"url": "https://example.test/second", "excerpts": ["More evidence"]},
            ]
        },
    }

    async def handler(request):
        assert str(request.url) == "https://search.parallel.ai/mcp"
        assert "AgentArea/" in request.headers["User-Agent"]
        assert "authorization" not in request.headers
        if request.method != "POST":
            return httpx2.Response(405)
        message = json.loads(request.content)
        calls.append(message)
        method = message["method"]
        if method == "initialize":
            result = {
                "protocolVersion": message["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test-search", "version": "1"},
            }
        elif method == "notifications/initialized":
            return httpx2.Response(202)
        elif method == "tools/list":
            result = {"tools": [{"name": "web_search", "inputSchema": {"type": "object"}}]}
        elif method == "tools/call":
            result = tool_result
        else:
            raise AssertionError(method)
        return httpx2.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result})

    def factory(**kwargs):
        return _REAL_MCP_CLIENT(transport=httpx2.MockTransport(handler), **kwargs)

    monkeypatch.setattr("agentarea_agents_sdk.tools.web_toolset.httpx2.AsyncClient", factory)
    return calls, tool_result


@pytest.mark.asyncio
async def test_unconfigured_search_dispatches_keyless_mcp_and_consumes_results(
    parallel_transport, monkeypatch
) -> None:
    monkeypatch.setenv("PARALLEL_API_KEY", "unused-ambient-key")
    calls, _ = parallel_transport
    toolset = create_code_tool_instance(
        "agentarea/web",
        extra_kwargs={"search_base_url": None, "search_session_id": "conversation-123"},
    )
    assert isinstance(toolset, WebToolset)
    executor = ToolExecutor()
    executor.register_tool(ToolsetAdapter(toolset))
    result = await executor.execute_tool(
        "web",
        {
            "action": "search_web",
            "search_web_query": "  current research  ",
            "search_web_max_results": 1,
        },
    )
    payload = json.loads(result["result"])
    assert payload == {
        "query": "current research",
        "results": [
            {
                "title": "Research",
                "url": "https://example.test/смета",
                "snippet": "Evidence",
                "engine": "parallel",
            }
        ],
    }
    assert "https://example.test/смета" in result["result"]
    arguments = next(c["params"]["arguments"] for c in calls if c["method"] == "tools/call")
    assert arguments == {
        "objective": "current research",
        "search_queries": ["current research"],
        "session_id": "conversation-123",
    }
    assert next(c["params"]["name"] for c in calls if c["method"] == "tools/call") == "web_search"
    assert calls[0]["method"] == "initialize"


@pytest.mark.asyncio
async def test_parallel_filters_urls_and_keeps_missing_titles(parallel_transport) -> None:
    payload = json.loads(await WebToolset().search_web("research"))
    assert [r["url"] for r in payload["results"]] == [
        "https://example.test/смета",
        "https://example.test/second",
    ]
    assert payload["results"][1]["title"] == "https://example.test/second"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["tool_error", "malformed", "invalid_excerpts"])
async def test_parallel_errors_are_visible(parallel_transport, failure) -> None:
    _, response = parallel_transport
    if failure == "tool_error":
        response.update(isError=True, content=[{"type": "text", "text": "Search unavailable"}])
    elif failure == "malformed":
        response["structuredContent"] = {"results": "invalid"}
    else:
        response["structuredContent"]["results"][0]["excerpts"] = "invalid"
    result = await WebToolset().search_web("research")
    assert result.startswith("Error searching the web with Parallel:")


@pytest.mark.asyncio
async def test_parallel_accepts_text_json_result(parallel_transport) -> None:
    _, response = parallel_transport
    response["content"] = [{"type": "text", "text": json.dumps(response.pop("structuredContent"))}]
    assert (
        json.loads(await WebToolset().search_web("research"))["results"][0]["snippet"] == "Evidence"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "transport", "cancel"])
async def test_parallel_transport_failure_and_cancellation(monkeypatch, failure) -> None:
    started = asyncio.Event()

    async def handler(request):
        started.set()
        if failure == "transport":
            raise httpx2.ConnectError("network unavailable", request=request)
        await asyncio.Event().wait()

    def factory(**kwargs):
        return _REAL_MCP_CLIENT(transport=httpx2.MockTransport(handler), **kwargs)

    monkeypatch.setattr("agentarea_agents_sdk.tools.web_toolset.httpx2.AsyncClient", factory)
    monkeypatch.setattr("agentarea_agents_sdk.tools.web_toolset._DEFAULT_TIMEOUT_SECONDS", 0.05)
    task = asyncio.create_task(WebToolset().search_web("research"))
    await started.wait()
    if failure == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        assert (await task).startswith("Error searching the web with Parallel:")


@pytest.mark.asyncio
async def test_configured_search_failure_never_switches_provider(monkeypatch, parallel_transport):
    def handler(request):
        return httpx.Response(503)

    monkeypatch.setattr(
        "agentarea_agents_sdk.tools.web_toolset.httpx.AsyncClient",
        _patched_client_factory(httpx.MockTransport(handler)),
    )
    assert (
        await WebToolset(search_base_url="https://search.test").search_web("research")
    ).startswith("Error searching the web:")
    assert parallel_transport[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("query,max_results", [("", 8), (" ", 8), ("q", 0), ("q", 21), ("q", True)])
async def test_invalid_search_does_not_make_requests(parallel_transport, query, max_results):
    assert (await WebToolset().search_web(query, max_results)).startswith("Error:")
    assert parallel_transport[0] == []


@pytest.mark.asyncio
async def test_disabled_search_does_not_make_requests(parallel_transport):
    result = await WebToolset(search_web=False).execute(action="search_web", search_web_query="q")
    assert "search_web is disabled" in result["result"]
    assert parallel_transport[0] == []


@pytest.mark.asyncio
async def test_html_page_is_returned_inline_with_text_and_links() -> None:
    body = (
        "<html><head><title>T</title><style>.hidden{color:red}</style></head>"
        "<body><script>alert(1)</script><p>смета</p><a href='/docs'>Docs</a></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert "AgentArea/" in request.headers["User-Agent"]
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
