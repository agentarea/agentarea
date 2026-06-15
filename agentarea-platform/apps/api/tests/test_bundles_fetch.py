"""Unit tests for the SSRF-guarded bundle source fetcher used by /v1/bundles/analyze.

The fetcher lets a landing-page deep-link (`/bundles/import?src=<url>`) hand the
platform a bundle URL instead of pasted text. It must reuse the same SSRF guard
(`validate_url`) as the other outbound-fetch endpoints and cap the body size.
"""

import httpx
import pytest
from agentarea_api.api.v1.bundles import _MAX_BUNDLE_BYTES, fetch_bundle_source
from agentarea_common.testing.flows import MainFlow


@pytest.mark.flow(MainFlow.BUNDLES)
@pytest.mark.asyncio
async def test_fetch_returns_text():
    transport = httpx.MockTransport(lambda _req: httpx.Response(200, text="name: demo"))
    out = await fetch_bundle_source(
        "http://example.test/bundle.yaml", allow_private=True, transport=transport
    )
    assert out == "name: demo"


@pytest.mark.asyncio
async def test_fetch_rejects_non_http_scheme():
    # Scheme check fires in validate_url before any network access.
    with pytest.raises(ValueError, match="scheme"):
        await fetch_bundle_source("file:///etc/passwd", allow_private=False)


@pytest.mark.asyncio
async def test_fetch_rejects_private_ip():
    # 169.254.169.254 is the cloud metadata endpoint — a classic SSRF target.
    with pytest.raises(ValueError, match="private/internal"):
        await fetch_bundle_source("http://169.254.169.254/latest", allow_private=False)


@pytest.mark.asyncio
async def test_fetch_rejects_oversize_body():
    big = "x" * (_MAX_BUNDLE_BYTES + 1)
    transport = httpx.MockTransport(lambda _req: httpx.Response(200, text=big))
    with pytest.raises(ValueError, match="exceeds"):
        await fetch_bundle_source(
            "http://example.test/big.yaml", allow_private=True, transport=transport
        )


@pytest.mark.asyncio
async def test_fetch_raises_on_http_error():
    transport = httpx.MockTransport(lambda _req: httpx.Response(404))
    with pytest.raises(httpx.HTTPStatusError):
        await fetch_bundle_source(
            "http://example.test/missing.yaml", allow_private=True, transport=transport
        )


@pytest.mark.asyncio
async def test_fetch_does_not_follow_redirects():
    # A redirect could bounce to an internal IP that bypasses the up-front
    # validate_url check, so redirects are treated as an error, not followed.
    transport = httpx.MockTransport(
        lambda _req: httpx.Response(302, headers={"location": "http://169.254.169.254/"})
    )
    with pytest.raises(httpx.HTTPStatusError):
        await fetch_bundle_source(
            "http://example.test/redir.yaml", allow_private=True, transport=transport
        )
