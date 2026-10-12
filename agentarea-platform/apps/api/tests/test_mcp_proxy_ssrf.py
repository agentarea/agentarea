"""SSRF guard for the MCP reverse proxy.

User-controlled URL-type upstreams are checked against private/metadata ranges
before the request (`_guard_upstream`, which answers 400) and sent on the pinned
client (`_upstream_client`), which resolves, vets and pins the address itself.
Internally-generated container/command upstreams pass through untouched.

All cases use numeric-IP hosts so no real DNS resolution happens in unit tests.
"""

import httpx
import pytest
from agentarea_api.api.v1 import mcp_proxy
from agentarea_api.api.v1.mcp_proxy import _guard_upstream, _upstream_client
from agentarea_common.utils.url_safety import (
    OutboundPolicy,
    SafeOutboundTransport,
    UnsafeDestinationError,
)


def test_container_upstream_passes_through_without_validation():
    # Internal docker host is private but legitimate and NOT user-supplied.
    _guard_upstream("http://mcp-abc123:8080/mcp", "docker", policy=OutboundPolicy())


def test_command_upstream_passes_through_without_validation():
    _guard_upstream("http://mcp-xyz:8080/mcp", "command", policy=OutboundPolicy())


def test_url_upstream_to_cloud_metadata_is_rejected():
    with pytest.raises(ValueError, match="private/internal"):
        _guard_upstream("http://169.254.169.254/latest/meta-data", "url", policy=OutboundPolicy())


def test_url_upstream_to_private_range_is_rejected():
    with pytest.raises(ValueError, match="private/internal"):
        _guard_upstream("http://10.0.0.5/mcp", "url", policy=OutboundPolicy())


def test_url_upstream_to_loopback_is_rejected():
    with pytest.raises(ValueError, match="private/internal"):
        _guard_upstream("http://127.0.0.1:9000/mcp", "url", policy=OutboundPolicy())


def test_public_url_upstream_passes_the_guard():
    _guard_upstream("https://1.1.1.1/mcp", "url", policy=OutboundPolicy())


def test_private_url_allowed_when_allow_private_set():
    _guard_upstream("http://10.0.0.5/mcp", "url", policy=OutboundPolicy(allow_private=True))


@pytest.mark.asyncio
async def test_a_url_upstream_is_sent_on_the_pinned_client():
    # The guard resolved the name once; the client resolves it again when it
    # dials, so a name that rebinds between the two is refused there.
    async with _upstream_client("url", policy=OutboundPolicy()) as client:
        with pytest.raises(UnsafeDestinationError):
            await client.get("http://10.0.0.5/mcp")


def _record_upstream(monkeypatch, *, resolves_to: str) -> list[tuple[str | None, str, str]]:
    sent: list[tuple[str | None, str, str]] = []

    def through(proxy: str | None = None) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            sent.append((proxy, request.url.host, request.headers["host"]))
            return httpx.Response(200)

        return httpx.MockTransport(handle)

    async def resolve(_host: str, _port: int) -> list[str]:
        return [resolves_to]

    monkeypatch.setattr(
        mcp_proxy,
        "safe_async_client",
        lambda *, policy, **kwargs: httpx.AsyncClient(
            transport=SafeOutboundTransport(policy, resolve=resolve, inner=through), **kwargs
        ),
    )
    return sent


@pytest.fixture
def proxied_egress(monkeypatch):
    """Egress goes through a forward proxy, as it does in RU production."""
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv(var.lower(), raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://egress-proxy:8888")
    monkeypatch.setenv("HTTP_PROXY", "http://egress-proxy:8888")


@pytest.mark.asyncio
async def test_a_proxied_url_upstream_goes_to_the_proxy_by_name(monkeypatch, proxied_egress):
    """A pinned IP cannot carry SNI through a CONNECT tunnel, so the proxy gets the name."""
    sent = _record_upstream(monkeypatch, resolves_to="93.184.216.34")

    async with _upstream_client("url", policy=OutboundPolicy()) as client:
        await client.get("https://mcp.example.com/mcp")

    assert sent == [("http://egress-proxy:8888", "mcp.example.com", "mcp.example.com")]


@pytest.mark.asyncio
async def test_an_unproxied_url_upstream_is_pinned_and_keeps_its_host_header(monkeypatch):
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv(var.lower(), raising=False)
    sent = _record_upstream(monkeypatch, resolves_to="93.184.216.34")

    async with _upstream_client("url", policy=OutboundPolicy()) as client:
        await client.get("https://mcp.example.com/mcp")

    assert sent == [(None, "93.184.216.34", "mcp.example.com")]


@pytest.mark.asyncio
async def test_a_container_upstream_reaches_the_gateway_unvetted(monkeypatch):
    # The demand gateway is an in-cluster address the platform builds itself.
    monkeypatch.setattr(
        mcp_proxy,
        "safe_async_client",
        lambda **_kw: pytest.fail("a gateway request must not go through the member client"),
    )
    async with _upstream_client("docker", policy=OutboundPolicy()) as client:
        assert not isinstance(client._transport, SafeOutboundTransport)
