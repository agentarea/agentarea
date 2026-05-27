"""Unit tests for the per-instance MCP reverse proxy."""

from types import SimpleNamespace

import pytest

from agentarea_api.api.v1.mcp_proxy import (
    _filter_inbound_headers,
    _filter_outbound_headers,
    _resolve_upstream_url,
)


# ----- _resolve_upstream_url -----


@pytest.mark.asyncio
async def test_resolve_upstream_url_url_type_from_server_remote_url():
    instance = SimpleNamespace(json_spec={}, server_spec_id="x", id="i")
    server_spec = SimpleNamespace(
        remote_url="https://mcp.clickup.com/mcp",
        cmd=None,
        json_spec={},
    )

    assert await _resolve_upstream_url(instance, server_spec) == "https://mcp.clickup.com/mcp"


@pytest.mark.asyncio
async def test_resolve_upstream_url_legacy_endpoint_url_on_instance():
    instance = SimpleNamespace(
        json_spec={"type": "url", "endpoint_url": "https://legacy.example/mcp"},
        id="i",
    )
    server_spec = SimpleNamespace(remote_url=None, cmd=None, json_spec={})

    assert await _resolve_upstream_url(instance, server_spec) == "https://legacy.example/mcp"


@pytest.mark.asyncio
async def test_resolve_upstream_url_docker_appends_mcp_path():
    instance = SimpleNamespace(
        json_spec={"type": "docker"},
        endpoint_url="http://mcp-abc:8000",
        id="i",
    )
    server_spec = SimpleNamespace(remote_url=None, cmd=None, json_spec={})

    assert await _resolve_upstream_url(instance, server_spec) == "http://mcp-abc:8000/mcp"


@pytest.mark.asyncio
async def test_resolve_upstream_url_docker_strips_trailing_slash():
    instance = SimpleNamespace(
        json_spec={"type": "docker"},
        endpoint_url="http://mcp-abc:8000/",
        id="i",
    )
    server_spec = SimpleNamespace(remote_url=None, cmd=None, json_spec={})

    assert await _resolve_upstream_url(instance, server_spec) == "http://mcp-abc:8000/mcp"


@pytest.mark.asyncio
async def test_resolve_upstream_url_url_type_returns_empty_without_remote_url():
    instance = SimpleNamespace(
        json_spec={"type": "url"},
        id="i",
    )
    server_spec = SimpleNamespace(remote_url=None, cmd=None, json_spec={})

    assert await _resolve_upstream_url(instance, server_spec) == ""


# ----- header filters -----


def test_filter_inbound_drops_authorization_and_host():
    headers = {
        "Authorization": "Bearer user-token",
        "Host": "api.agentarea.dev",
        "Content-Type": "application/json",
        "Accept": "application/json,text/event-stream",
        "Mcp-Session-Id": "abc",
    }

    out = _filter_inbound_headers(headers)

    assert "Authorization" not in out
    assert "Host" not in out
    assert out["Content-Type"] == "application/json"
    assert out["Mcp-Session-Id"] == "abc"


def test_filter_inbound_drops_hop_by_hop():
    headers = {
        "Connection": "close",
        "Transfer-Encoding": "chunked",
        "Upgrade": "websocket",
        "Content-Type": "application/json",
    }

    out = _filter_inbound_headers(headers)

    assert "Connection" not in out
    assert "Transfer-Encoding" not in out
    assert "Upgrade" not in out
    assert out["Content-Type"] == "application/json"


def test_filter_outbound_drops_content_length_and_transfer_encoding():
    # Upstream may send chunked or pre-sized; we let StreamingResponse manage these.
    headers = {
        "Content-Length": "123",
        "Transfer-Encoding": "chunked",
        "Content-Type": "text/event-stream",
        "Mcp-Session-Id": "abc",
    }

    out = _filter_outbound_headers(headers)

    assert "Content-Length" not in out
    assert "Transfer-Encoding" not in out
    assert out["Content-Type"] == "text/event-stream"
    assert out["Mcp-Session-Id"] == "abc"
