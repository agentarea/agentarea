"""End-to-end tests for creating shared workspaces and inviting into them.

Exercises the real running stack (Kratos + backend API). Covers the gap that
``WorkspaceService.create_shared`` had no HTTP entry point: a user must be able
to create a brand-new shared workspace, have it show up in their list, and
invite another (freshly registered) user into it.

Run with:
    uv run pytest -m integration tests/e2e/api/test_workspace_create.py -v
"""

from __future__ import annotations

import httpx
import pytest


def _list_workspaces(client: httpx.Client) -> list[dict]:
    resp = client.get("/v1/workspaces")
    resp.raise_for_status()
    return resp.json()


@pytest.mark.integration
def test_create_shared_workspace(alice, alice_client: httpx.Client) -> None:
    """Alice creates a shared workspace; it is distinct from her personal one."""
    resp = alice_client.post("/v1/workspaces", json={"name": "Team Rocket"})
    assert resp.status_code == 201, resp.text
    ws = resp.json()

    assert ws["type"] == "shared"
    assert ws["name"] == "Team Rocket"
    assert ws["slug"]  # slug derived from name
    # Shared workspaces get a generated id; never the owner's personal id.
    assert ws["id"] != alice.identity_id

    # It shows up in Alice's reachable workspaces (personal + the new shared one).
    workspaces = _list_workspaces(alice_client)
    ids = {w["id"] for w in workspaces}
    assert alice.identity_id in ids, "personal workspace missing"
    assert ws["id"] in ids, "newly created shared workspace not listed"


@pytest.mark.integration
def test_empty_name_rejected(alice_client: httpx.Client) -> None:
    resp = alice_client.post("/v1/workspaces", json={"name": "   "})
    assert resp.status_code == 422, resp.text


@pytest.mark.integration
def test_invite_into_new_workspace(
    alice,
    alice_client: httpx.Client,
    bob,
    bob_client: httpx.Client,
) -> None:
    """Full flow: Alice creates a shared workspace, invites Bob (a separately
    registered user), Bob accepts, and Bob becomes a member of the *shared*
    workspace — not Alice's personal one."""
    ws = (
        alice_client.post("/v1/workspaces", json={"name": "Shared Project"})
        .raise_for_status()
        .json()
    )
    workspace_id = ws["id"]

    # Bob is not a member yet — he can't read the shared workspace's invitations.
    blocked = bob_client.get(f"/v1/workspaces/{workspace_id}/invitations")
    assert blocked.status_code == 403, blocked.text

    invitation = (
        alice_client.post(
            f"/v1/workspaces/{workspace_id}/invitations",
            json={"email": bob.email},
        )
        .raise_for_status()
        .json()
    )
    assert invitation["workspace_id"] == workspace_id

    accept = bob_client.post("/v1/invitations/accept", json={"token": invitation["token"]})
    assert accept.status_code == 200, accept.text
    assert accept.json()["workspace_id"] == workspace_id

    # Bob now reaches the shared workspace and appears in its member list.
    members = bob_client.get(f"/v1/workspaces/{workspace_id}/members").raise_for_status().json()
    member_ids = {m["user_id"] for m in members}
    assert bob.identity_id in member_ids

    bob_workspaces = {w["id"] for w in _list_workspaces(bob_client)}
    assert workspace_id in bob_workspaces, "shared workspace not in Bob's list"
