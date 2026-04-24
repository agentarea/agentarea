"""Workspace isolation: Alice's resources must be invisible to Bob."""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.integration
def test_project_list_is_scoped_per_user(
    alice_client: httpx.Client, bob_client: httpx.Client
) -> None:
    alice_resp = alice_client.post(
        "/v1/projects/", json={"name": "alice-proj", "description": "x"}
    )
    alice_resp.raise_for_status()
    alice_project_id = alice_resp.json()["id"]

    bob_resp = bob_client.post(
        "/v1/projects/", json={"name": "bob-proj", "description": "y"}
    )
    bob_resp.raise_for_status()
    bob_project_id = bob_resp.json()["id"]

    alice_ids = {p["id"] for p in alice_client.get("/v1/projects/").json()}
    bob_ids = {p["id"] for p in bob_client.get("/v1/projects/").json()}

    assert alice_project_id in alice_ids
    assert bob_project_id not in alice_ids
    assert bob_project_id in bob_ids
    assert alice_project_id not in bob_ids


@pytest.mark.integration
def test_cross_workspace_get_returns_404(
    alice_client: httpx.Client, bob_client: httpx.Client
) -> None:
    alice_project_id = (
        alice_client.post("/v1/projects/", json={"name": "alice-priv"})
        .raise_for_status()
        .json()["id"]
    )

    resp = bob_client.get(f"/v1/projects/{alice_project_id}")
    assert resp.status_code == 404, f"Bob should not see Alice's project, got {resp.status_code}"


@pytest.mark.integration
def test_cross_workspace_delete_is_blocked(
    alice_client: httpx.Client, bob_client: httpx.Client
) -> None:
    alice_project_id = (
        alice_client.post("/v1/projects/", json={"name": "alice-victim"})
        .raise_for_status()
        .json()["id"]
    )

    del_resp = bob_client.delete(f"/v1/projects/{alice_project_id}")
    assert del_resp.status_code in (403, 404), f"got {del_resp.status_code}"

    verify = alice_client.get(f"/v1/projects/{alice_project_id}")
    assert verify.status_code == 200, "Alice's project must survive Bob's delete attempt"
