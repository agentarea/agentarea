from __future__ import annotations

import httpx
import pytest


@pytest.mark.integration
def test_openapi_connections_preview_valid_spec(alice_client: httpx.Client) -> None:
    resp = alice_client.post(
        "/v1/openapi-connections/preview-spec",
        json={
            "spec_url": "https://petstore3.swagger.io/api/v3/openapi.json",
        },
    )
    assert resp.status_code == 200, resp.text[:200]
    body = resp.json()
    assert "operations" in body or "tools" in body, f"Unexpected preview response: {body}"


@pytest.mark.integration
def test_openapi_connections_preview_invalid_url(alice_client: httpx.Client) -> None:
    resp = alice_client.post(
        "/v1/openapi-connections/preview-spec",
        json={"spec_url": "https://example.com/nonexistent-openapi.json"},
    )
    assert resp.status_code in (400, 422, 502), (
        f"Expected error for bad URL, got {resp.status_code}: {resp.text[:200]}"
    )


@pytest.mark.integration
def test_openapi_connections_discover_tools_on_connection(
    alice_client: httpx.Client,
) -> None:
    conn = alice_client.post(
        "/v1/openapi-connections/",
        json={
            "name": "petstore-preview",
            "base_url": "https://petstore3.swagger.io/api/v3",
            "spec_url": "https://petstore3.swagger.io/api/v3/openapi.json",
        },
    ).raise_for_status().json()

    discover = alice_client.post(
        f"/v1/openapi-connections/{conn['id']}/discover-tools"
    )
    assert discover.status_code == 200, discover.text[:200]
    body = discover.json()
    assert "tools" in body or "operations" in body, f"Unexpected discover response: {body}"

    alice_client.delete(f"/v1/openapi-connections/{conn['id']}")
