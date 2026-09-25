"""Focused tests for MCP client era negotiation and verdict caching."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import ClassVar
from unittest.mock import MagicMock

import httpx2
import pytest
from agentarea_mcp.application import mcp_client
from mcp import MCPError
from mcp.server.mcpserver import MCPServer
from mcp_types import DiscoverResult, ServerCapabilities


class _Store:
    def __init__(self, value=None):
        self.value = value
        self.deleted = []
        self.writes = []

    async def get(self, key):
        return self.value

    async def set(self, key, value):
        self.writes.append((key, value))
        self.value = value

    async def delete(self, key):
        self.deleted.append(key)
        self.value = None


class _FakeClient:
    instances: ClassVar[list[_FakeClient]] = []
    outcomes: ClassVar[list[object]] = []

    def __init__(self, server, *, mode="auto", prior_discover=None, **kwargs):
        self.server = server
        self.mode = mode
        self.prior_discover = prior_discover
        self.protocol_version = "2026-07-28" if mode != "legacy" else "2025-11-25"
        self.session = MagicMock()
        self.session.discover_result = None
        if mode == "auto":
            self.session.discover_result = DiscoverResult(
                supported_versions=["2026-07-28"], capabilities=ServerCapabilities()
            )
        self._outcome = self.outcomes.pop(0) if self.outcomes else None
        self.__class__.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def call_tool(self, *_args, **_kwargs):
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self._outcome


class _LegacyOnlyClient(_FakeClient):
    def __init__(self, server, *, mode="auto", prior_discover=None, **kwargs):
        super().__init__(server, mode=mode, prior_discover=prior_discover, **kwargs)
        if mode == "auto":
            self.protocol_version = "2025-11-25"
            self.session.discover_result = None


@asynccontextmanager
async def _transport(_url, **_kwargs):
    yield object()


@pytest.fixture(autouse=True)
def _reset_fake(monkeypatch):
    _FakeClient.instances = []
    _FakeClient.outcomes = [object()]
    monkeypatch.setattr(mcp_client, "Client", _FakeClient)
    monkeypatch.setattr(mcp_client, "streamable_http_client", _transport)
    monkeypatch.setattr(mcp_client, "sse_client", _transport)
    return


@pytest.mark.asyncio
async def test_unknown_connection_uses_auto_and_stores_modern_discover_result():
    store = _Store()
    async with mcp_client.connected_mcp_client(
        "https://mcp.example",
        {},
        3.0,
        verdict_key="instance:fp",
        verdict_store=store,
        httpx_client_factory=mcp_client.platform_client_factory,
    ) as client:
        await client.call_tool("tool", {})

    assert _FakeClient.instances[0].mode == "auto"
    assert store.writes[0][0] == "instance:fp"
    assert store.writes[0][1] != mcp_client.LEGACY_VERDICT
    assert DiscoverResult.model_validate_json(store.writes[0][1]).supported_versions == [
        "2026-07-28"
    ]


@pytest.mark.asyncio
async def test_unknown_connection_records_legacy_verdict_after_auto_fallback(monkeypatch):
    monkeypatch.setattr(mcp_client, "Client", _LegacyOnlyClient)
    store = _Store()

    async with mcp_client.connected_mcp_client(
        "https://mcp.example",
        {},
        3.0,
        verdict_key="instance:fp",
        verdict_store=store,
        httpx_client_factory=mcp_client.platform_client_factory,
    ) as client:
        await client.call_tool("tool", {})

    assert _LegacyOnlyClient.instances[0].mode == "auto"
    assert _LegacyOnlyClient.instances[0].protocol_version == "2025-11-25"
    assert store.writes == [("instance:fp", mcp_client.LEGACY_VERDICT)]


@pytest.mark.asyncio
async def test_cached_modern_verdict_pins_mode_without_probe():
    discover = DiscoverResult(supported_versions=["2026-07-28"], capabilities=ServerCapabilities())
    store = _Store(discover.model_dump_json())
    async with mcp_client.connected_mcp_client(
        "https://mcp.example",
        {},
        3.0,
        verdict_key="instance:fp",
        verdict_store=store,
        httpx_client_factory=mcp_client.platform_client_factory,
    ) as client:
        await client.call_tool("tool", {})

    assert _FakeClient.instances[0].mode == "2026-07-28"
    assert _FakeClient.instances[0].prior_discover.supported_versions == ["2026-07-28"]
    assert store.writes == []


@pytest.mark.asyncio
async def test_cached_legacy_verdict_uses_legacy_mode():
    store = _Store(mcp_client.LEGACY_VERDICT)
    async with mcp_client.connected_mcp_client(
        "https://mcp.example",
        {},
        3.0,
        verdict_key="instance:fp",
        verdict_store=store,
        httpx_client_factory=mcp_client.platform_client_factory,
    ) as client:
        await client.call_tool("tool", {})

    assert _FakeClient.instances[0].mode == "legacy"
    assert store.writes == []


@pytest.mark.asyncio
async def test_cached_protocol_error_drops_verdict_and_retries_once_with_auto():
    store = _Store(mcp_client.LEGACY_VERDICT)
    _FakeClient.outcomes = [MCPError(-32022, "unsupported"), object()]

    async with mcp_client.connected_mcp_client(
        "https://mcp.example",
        {},
        3.0,
        verdict_key="instance:fp",
        verdict_store=store,
        httpx_client_factory=mcp_client.platform_client_factory,
    ) as client:
        await client.call_tool("tool", {})

    assert [item.mode for item in _FakeClient.instances] == ["legacy", "auto"]
    assert store.deleted == ["instance:fp"]
    assert store.writes


@pytest.mark.asyncio
async def test_non_negotiation_tool_error_is_not_retried():
    store = _Store(mcp_client.LEGACY_VERDICT)
    _FakeClient.outcomes = [MCPError(-32001, "tool failed")]

    with pytest.raises(MCPError) as exc_info:
        async with mcp_client.connected_mcp_client(
            "https://mcp.example",
            {},
            3.0,
            verdict_key="instance:fp",
            verdict_store=store,
            httpx_client_factory=mcp_client.platform_client_factory,
        ) as client:
            await client.call_tool("tool", {})

    assert exc_info.value.code == -32001
    assert len(_FakeClient.instances) == 1
    assert store.deleted == []


@pytest.mark.asyncio
async def test_real_mcpserver_streamable_http_negotiates_modern_protocol():
    from mcp import Client as RealClient
    from mcp.client.streamable_http import streamable_http_client as real_transport
    from mcp.server.transport_security import TransportSecuritySettings

    server = MCPServer(name="in-process")

    def ping() -> str:
        return "pong"

    server.add_tool(ping, name="ping")
    app = server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=["127.0.0.1"],
            allowed_origins=["http://127.0.0.1"],
        ),
    )

    requests: list[dict[str, str]] = []

    async def recording_app(scope, receive, send):
        if scope["type"] == "http":
            requests.append(
                {key.decode().lower(): value.decode() for key, value in scope["headers"]}
            )
        await app(scope, receive, send)

    def make_http_client(*, headers=None, timeout=None, **_kwargs):
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=recording_app),
            headers=headers,
            timeout=timeout,
        )

    # This test exercises the installed v2 transport and server, not the fakes
    # used by the verdict unit tests above.
    mcp_client_module = mcp_client
    mcp_client_module.Client = RealClient
    mcp_client_module.streamable_http_client = real_transport
    try:
        async with app.router.lifespan_context(app):
            async with mcp_client_module.connected_mcp_client(
                "http://127.0.0.1/",
                {},
                5.0,
                transport="streamable-http",
                httpx_client_factory=make_http_client,
            ) as client:
                assert client.protocol_version == "2026-07-28"
                result = await client.list_tools()
                assert any(request.get("mcp-method") == "server/discover" for request in requests)
                assert any(request.get("mcp-method") == "tools/list" for request in requests)
                assert all("mcp-session-id" not in request for request in requests)
                assert all(
                    request.get("mcp-protocol-version") == "2026-07-28"
                    for request in requests
                    if request.get("mcp-method") in {"server/discover", "tools/list"}
                )
    finally:
        mcp_client_module.Client = _FakeClient
        mcp_client_module.streamable_http_client = _transport
    assert [tool.name for tool in result.tools] == ["ping"]
