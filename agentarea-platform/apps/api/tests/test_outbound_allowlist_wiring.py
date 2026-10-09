"""AGENTAREA_HTTP_PRIVATE_ALLOWLIST reaches every path that dials a member's URL.

The MCP proxy, bundle fetch and OpenAPI connections gated on AGENTAREA_HTTP_ALLOW_PRIVATE
alone, so an endpoint the allowlist admitted passed validate-connection and
was then refused on the tool call.
"""

import httpx
import pytest
from agentarea_api.api.v1 import bundles
from agentarea_api.api.v1.bundles import fetch_bundle_source
from agentarea_api.api.v1.mcp_proxy import _guard_upstream
from agentarea_common.utils.url_safety import OutboundPolicy, SafeOutboundTransport
from agentarea_openapi.application.url_validator import validate_url

LOCAL = OutboundPolicy(private_allowlist=("127.0.0.0/8",))


def test_the_openapi_validator_admits_an_allowlisted_private_address():
    assert validate_url("http://127.0.0.1:8080/spec.json", policy=LOCAL) == ["127.0.0.1"]
    with pytest.raises(ValueError, match="private/internal"):
        validate_url("http://10.0.0.5/spec.json", policy=LOCAL)


def test_the_mcp_proxy_admits_an_allowlisted_upstream():
    _guard_upstream("http://127.0.0.1:9000/mcp", "url", policy=LOCAL)
    with pytest.raises(ValueError, match="private/internal"):
        _guard_upstream("http://10.0.0.5/mcp", "url", policy=LOCAL)


@pytest.mark.asyncio
async def test_a_bundle_on_an_allowlisted_address_is_fetched(monkeypatch):
    def client(*, policy, **kwargs):
        inner = httpx.MockTransport(lambda _req: httpx.Response(200, text="name: demo"))
        transport = SafeOutboundTransport(policy, inner=lambda proxy=None: inner)
        return httpx.AsyncClient(transport=transport, **kwargs)

    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv(var.lower(), raising=False)
    monkeypatch.setattr(bundles, "safe_async_client", client)

    out = await fetch_bundle_source("http://127.0.0.1:8000/bundle.yaml", policy=LOCAL)

    assert out == "name: demo"


def test_the_policy_is_the_deployments(monkeypatch):
    from agentarea_common.config import get_settings

    monkeypatch.setenv("AGENTAREA_HTTP_PRIVATE_ALLOWLIST", "127.0.0.0/8")
    monkeypatch.delenv("AGENTAREA_HTTP_ALLOW_PRIVATE", raising=False)
    get_settings.cache_clear()
    try:
        policy = OutboundPolicy.from_env()
    finally:
        get_settings.cache_clear()

    assert validate_url("http://127.0.0.1/", policy=policy) == ["127.0.0.1"]
