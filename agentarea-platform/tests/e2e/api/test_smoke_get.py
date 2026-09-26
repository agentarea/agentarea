"""Smoke test: hit every GET endpoint with a valid JWT and assert non-5xx.

Goal: catch broken imports, DI regressions, migrations, auth wiring. Does not
assert business logic — only that each route is reachable and doesn't blow up.
"""

from __future__ import annotations

import httpx
import pytest

from .conftest import WorkspaceClient

# Endpoints we expect to work for any authenticated user with an empty workspace,
# relative to that workspace. 404 and 405 are allowed — some routes are
# intentionally item-only or POST-only.
SAFE_GET_ENDPOINTS = [
    "/agents/",
    "/agents/tools",
    "/tasks/",
    "/triggers/",
    "/triggers/catalog",
    "/triggers/health",
    "/mcp-server-instances/",
    "/mcp-auth-configs/",
    "/registries/",
    "/provider-specs/",
    "/provider-configs/",
    "/model-instances/",
    "/openapi-connections/",
    "/skills",
    "/audit-logs/",
    "/inbox/",
    "/api-keys/",
    "/projects/",
    "/export",
    "/network/topology",
]


@pytest.mark.integration
@pytest.mark.parametrize("path", SAFE_GET_ENDPOINTS)
def test_get_endpoint_does_not_5xx(alice_client: WorkspaceClient, path: str) -> None:
    resp = alice_client.get(f"{alice_client.ws}{path}")
    assert resp.status_code < 500, (
        f"GET {path} returned {resp.status_code}: {resp.text[:200]}"
    )


@pytest.mark.integration
def test_missing_auth_returns_401(anon_client: httpx.Client) -> None:
    resp = anon_client.get("/v1/workspaces/any-workspace/agents/")
    assert resp.status_code == 401


@pytest.mark.integration
def test_invalid_bearer_returns_401(anon_client: httpx.Client) -> None:
    resp = anon_client.get(
        "/v1/workspaces/any-workspace/agents/",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401
