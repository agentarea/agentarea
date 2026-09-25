"""OUTBOUND_PRIVATE_ALLOWLIST reaches every path that dials a member's URL.

The MCP proxy, bundle fetch and OpenAPI connections gated on ALLOW_PRIVATE_URLS
alone, so an endpoint the allowlist admitted passed validate-connection and
was then refused on the tool call.
"""

import httpx
import pytest
from agentarea_api.api.v1.bundles import fetch_bundle_source
from agentarea_api.api.v1.mcp_proxy import _guard_and_pin_upstream
from agentarea_common.utils.url_safety import OutboundPolicy
from agentarea_openapi.application.url_validator import validate_url

LOCAL = OutboundPolicy(private_allowlist=("127.0.0.0/8",))


def test_the_openapi_validator_admits_an_allowlisted_private_address():
    assert validate_url("http://127.0.0.1:8080/spec.json", policy=LOCAL) == ["127.0.0.1"]
    with pytest.raises(ValueError, match="private/internal"):
        validate_url("http://10.0.0.5/spec.json", policy=LOCAL)


def test_the_mcp_proxy_admits_an_allowlisted_upstream():
    target, _host, _ext = _guard_and_pin_upstream("http://127.0.0.1:9000/mcp", "url", policy=LOCAL)

    assert isinstance(target, httpx.URL)
    assert target.host == "127.0.0.1"


@pytest.mark.asyncio
async def test_a_bundle_on_an_allowlisted_address_is_fetched():
    transport = httpx.MockTransport(lambda _req: httpx.Response(200, text="name: demo"))

    out = await fetch_bundle_source(
        "http://127.0.0.1:8000/bundle.yaml", policy=LOCAL, transport=transport
    )

    assert out == "name: demo"


def test_the_policy_is_the_deployments(monkeypatch):
    monkeypatch.setenv("OUTBOUND_PRIVATE_ALLOWLIST", "127.0.0.0/8")
    monkeypatch.delenv("ALLOW_PRIVATE_URLS", raising=False)

    assert validate_url("http://127.0.0.1/", policy=OutboundPolicy.from_env()) == ["127.0.0.1"]
