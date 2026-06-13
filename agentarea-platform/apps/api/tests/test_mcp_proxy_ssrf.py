"""SSRF guard for the MCP reverse proxy.

`_guard_and_pin_upstream` is the single chokepoint: user-controlled URL-type
upstreams are validated against private/metadata ranges and pinned to a
resolved IP (anti-DNS-rebinding); internally-generated container/command
upstreams pass through untouched.

All cases use numeric-IP hosts so no real DNS resolution happens in unit tests.
"""

import httpx
import pytest
from agentarea_api.api.v1.mcp_proxy import _guard_and_pin_upstream


def test_container_upstream_passes_through_without_validation():
    # Internal docker host is private but legitimate and NOT user-supplied.
    target, host, ext = _guard_and_pin_upstream(
        "http://mcp-abc123:8080/mcp", "docker", allow_private=False
    )
    assert target == "http://mcp-abc123:8080/mcp"
    assert host is None
    assert ext is None


def test_command_upstream_passes_through_without_validation():
    target, host, ext = _guard_and_pin_upstream(
        "http://mcp-xyz:8080/mcp", "command", allow_private=False
    )
    assert target == "http://mcp-xyz:8080/mcp"


def test_url_upstream_to_cloud_metadata_is_rejected():
    with pytest.raises(ValueError, match="private/internal"):
        _guard_and_pin_upstream(
            "http://169.254.169.254/latest/meta-data", "url", allow_private=False
        )


def test_url_upstream_to_private_range_is_rejected():
    with pytest.raises(ValueError, match="private/internal"):
        _guard_and_pin_upstream("http://10.0.0.5/mcp", "url", allow_private=False)


def test_url_upstream_to_loopback_is_rejected():
    with pytest.raises(ValueError, match="private/internal"):
        _guard_and_pin_upstream("http://127.0.0.1:9000/mcp", "url", allow_private=False)


def test_public_url_upstream_is_pinned_to_resolved_ip():
    target, host, ext = _guard_and_pin_upstream("https://1.1.1.1/mcp", "url", allow_private=False)
    assert isinstance(target, httpx.URL)
    assert target.host == "1.1.1.1"
    assert target.scheme == "https"
    assert target.path == "/mcp"
    # Host header + SNI preserve the original hostname (here, the literal IP).
    assert host == "1.1.1.1"
    assert ext == {"sni_hostname": "1.1.1.1"}


def test_private_url_allowed_when_allow_private_set():
    # Self-hosted escape hatch: validation is skipped, upstream still pinned.
    target, host, ext = _guard_and_pin_upstream("http://10.0.0.5/mcp", "url", allow_private=True)
    assert isinstance(target, httpx.URL)
    assert target.host == "10.0.0.5"
    assert target.path == "/mcp"
