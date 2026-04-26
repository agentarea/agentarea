"""Smoke test: hit every GET endpoint with a valid JWT and assert non-5xx.

Goal: catch broken imports, DI regressions, migrations, auth wiring. Does not
assert business logic — only that each route is reachable and doesn't blow up.
"""

from __future__ import annotations

import httpx
import pytest

# Endpoints we expect to work for any authenticated user with an empty workspace.
# 404 and 405 are allowed — some routes are intentionally item-only or POST-only.
SAFE_GET_ENDPOINTS = [
    "/health",
    "/v1/agents/",
    "/v1/agents/tools",
    "/v1/tasks/",
    "/v1/triggers/",
    "/v1/triggers/catalog",
    "/v1/triggers/health",
    "/v1/mcp-server-instances/",
    "/v1/mcp-auth-configs/",
    "/v1/registries/",
    "/v1/provider-specs/",
    "/v1/provider-configs/",
    "/v1/model-instances/",
    "/v1/openapi-connections/",
    "/v1/skills",
    "/v1/audit-logs/",
    "/v1/inbox/",
    "/v1/api-keys/",
    "/v1/projects/",
    "/v1/workspace/export",
    "/v1/network/topology",
]


@pytest.mark.integration
@pytest.mark.parametrize("path", SAFE_GET_ENDPOINTS)
def test_get_endpoint_does_not_5xx(alice_client: httpx.Client, path: str) -> None:
    resp = alice_client.get(path)
    assert resp.status_code < 500, (
        f"GET {path} returned {resp.status_code}: {resp.text[:200]}"
    )


@pytest.mark.integration
def test_missing_auth_returns_401(anon_client: httpx.Client) -> None:
    resp = anon_client.get("/v1/agents/")
    assert resp.status_code == 401


@pytest.mark.integration
def test_invalid_bearer_returns_401(anon_client: httpx.Client) -> None:
    resp = anon_client.get(
        "/v1/agents/", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert resp.status_code == 401
