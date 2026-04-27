from __future__ import annotations

import httpx
import pytest


@pytest.mark.integration
def test_mcp_server_instance_validate_valid_spec(alice_client: httpx.Client) -> None:
    resp = alice_client.post(
        "/v1/mcp-server-instances/validate",
        json={
            "name": "validate-ok",
            "type": "docker",
            "endpoint_url": "",
            "headers": {},
        },
    )
    assert resp.status_code == 200, resp.text[:200]
    body = resp.json()
    assert body.get("valid") is True or "errors" not in body, (
        f"Expected valid spec, got errors: {body}"
    )


@pytest.mark.integration
def test_mcp_server_instance_validate_invalid_spec(alice_client: httpx.Client) -> None:
    resp = alice_client.post(
        "/v1/mcp-server-instances/validate",
        json={
            "name": "validate-bad",
            "json_spec": {"invalid_field": "value"},
        },
    )
    assert resp.status_code in (200, 400, 422), resp.text[:200]
    body = resp.json()
    if resp.status_code == 200:
        assert body.get("valid") is False or "errors" in body, (
            f"Expected validation errors, got: {body}"
        )


@pytest.mark.integration
def test_mcp_server_instance_validate_connection(alice_client: httpx.Client) -> None:
    resp = alice_client.post(
        "/v1/mcp-server-instances/validate-connection",
        json={
            "url": "http://localhost:9999",
            "headers": {},
        },
    )
    assert resp.status_code in (200, 400, 502, 503), resp.text[:200]


@pytest.mark.integration
def test_mcp_server_instance_check_config(alice_client: httpx.Client) -> None:
    resp = alice_client.post(
        "/v1/mcp-server-instances/check",
        json={
            "name": "check-test",
            "json_spec": {
                "name": "check-server",
                "version": "1.0.0",
                "image": "alpine:latest",
                "port": 8080,
            },
        },
    )
    assert resp.status_code in (200, 503), resp.text[:200]
    if resp.status_code == 200:
        body = resp.json()
        assert "valid" in body or "errors" in body or "status" in body, (
            f"Unexpected check response: {body}"
        )
    else:
        pytest.skip("Go MCP manager not available for /check endpoint")
