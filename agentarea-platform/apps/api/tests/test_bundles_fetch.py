"""Unit tests for the SSRF-guarded bundle source fetcher used by /v1/bundles/analyze.

The fetcher lets a landing-page deep-link (`/bundles/import?src=<url>`) hand the
platform a bundle URL instead of pasted text. It must reuse the same SSRF guard
(`validate_url`) as the other outbound-fetch endpoints and cap the body size.
"""

import httpx
import pytest
from agentarea_api.api.v1 import bundles
from agentarea_api.api.v1.bundles import _MAX_BUNDLE_BYTES, fetch_bundle_source
from agentarea_common.testing.flows import MainFlow
from agentarea_common.utils.url_safety import (
    OutboundPolicy,
    SafeOutboundTransport,
    UnsafeDestinationError,
)


def _serve(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    monkeypatch.setattr(
        bundles,
        "safe_async_client",
        lambda *, policy, **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )


@pytest.mark.flow(MainFlow.BUNDLES)
@pytest.mark.asyncio
async def test_fetch_returns_text(monkeypatch):
    _serve(monkeypatch, lambda _req: httpx.Response(200, text="name: demo"))
    out = await fetch_bundle_source(
        "http://example.test/bundle.yaml", policy=OutboundPolicy(allow_private=True)
    )
    assert out == "name: demo"


@pytest.mark.asyncio
async def test_fetch_rejects_non_http_scheme():
    # Scheme check fires in validate_url before any network access.
    with pytest.raises(ValueError, match="scheme"):
        await fetch_bundle_source("file:///etc/passwd", policy=OutboundPolicy())


@pytest.mark.asyncio
async def test_fetch_rejects_private_ip():
    # 169.254.169.254 is the cloud metadata endpoint — a classic SSRF target.
    with pytest.raises(ValueError, match="private/internal"):
        await fetch_bundle_source("http://169.254.169.254/latest", policy=OutboundPolicy())


@pytest.mark.asyncio
async def test_fetch_rejects_oversize_body(monkeypatch):
    big = "x" * (_MAX_BUNDLE_BYTES + 1)
    _serve(monkeypatch, lambda _req: httpx.Response(200, text=big))
    with pytest.raises(ValueError, match="exceeds"):
        await fetch_bundle_source(
            "http://example.test/big.yaml", policy=OutboundPolicy(allow_private=True)
        )


@pytest.mark.asyncio
async def test_fetch_raises_on_http_error(monkeypatch):
    _serve(monkeypatch, lambda _req: httpx.Response(404))
    with pytest.raises(httpx.HTTPStatusError):
        await fetch_bundle_source(
            "http://example.test/missing.yaml", policy=OutboundPolicy(allow_private=True)
        )


@pytest.mark.asyncio
async def test_fetch_does_not_follow_redirects(monkeypatch):
    # A redirect could bounce to an internal IP that bypasses the up-front
    # validate_url check, so redirects are treated as an error, not followed.
    _serve(
        monkeypatch,
        lambda _req: httpx.Response(302, headers={"location": "http://169.254.169.254/"}),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await fetch_bundle_source(
            "http://example.test/redir.yaml", policy=OutboundPolicy(allow_private=True)
        )


def _through_pinned_client(monkeypatch, *, resolves_to: str) -> list[tuple[str | None, str]]:
    """Send bundle fetches through the real pinned transport, recording where each went."""
    sent: list[tuple[str | None, str]] = []

    def through(proxy: str | None = None) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            sent.append((proxy, request.url.host))
            return httpx.Response(200, text="name: demo")

        return httpx.MockTransport(handle)

    async def resolve(_host: str, _port: int) -> list[str]:
        return [resolves_to]

    monkeypatch.setattr(bundles, "validate_url", lambda *_a, **_k: ["93.184.216.34"])
    monkeypatch.setattr(
        bundles,
        "safe_async_client",
        lambda *, policy, **kwargs: httpx.AsyncClient(
            transport=SafeOutboundTransport(policy, resolve=resolve, inner=through), **kwargs
        ),
    )
    return sent


@pytest.mark.asyncio
async def test_a_bundle_fetched_through_a_proxy_names_the_host_not_its_address(monkeypatch):
    # Pinning the URL to an IP by hand sent CONNECT <ip>:443 through HTTPS_PROXY,
    # and TLS was then verified against the IP, as the OpenAPI spec fetch did (#691).
    monkeypatch.setenv("HTTPS_PROXY", "http://egress-proxy:8888")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    sent = _through_pinned_client(monkeypatch, resolves_to="93.184.216.34")

    out = await fetch_bundle_source(
        "https://bundles.example.com/demo.yaml", policy=OutboundPolicy()
    )

    assert out == "name: demo"
    assert sent == [("http://egress-proxy:8888", "bundles.example.com")]


@pytest.mark.asyncio
async def test_a_bundle_host_that_rebinds_to_a_private_address_is_refused(monkeypatch):
    # The pre-check saw a public address; the name answers privately when dialled.
    for var in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv(var.lower(), raising=False)
    sent = _through_pinned_client(monkeypatch, resolves_to="169.254.169.254")

    with pytest.raises(UnsafeDestinationError):
        await fetch_bundle_source(
            "https://bundles.example.com/demo.yaml", policy=OutboundPolicy()
        )

    assert sent == []
