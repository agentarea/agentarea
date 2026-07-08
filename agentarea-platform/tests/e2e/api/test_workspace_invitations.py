"""End-to-end tests for workspace invitation flow.

Covers:
  1. happy path — Alice creates invite, Bob accepts, membership exists
  2. consumed token — second accept of same token fails (or is idempotent
     when Bob accepts twice)
  3. expired token — accept after expiry fails 410
  4. revoked token — accept after revoke fails 410
  5. cross-workspace listing blocked — Bob can't list Alice's invitations
  6. double-accept idempotent — Bob accepting twice returns same membership
"""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest


def _members(client: httpx.Client, workspace_id: str) -> list[dict]:
    resp = client.get(f"/v1/workspaces/{workspace_id}/members")
    resp.raise_for_status()
    return resp.json()


def _create_invitation(
    alice_client: httpx.Client, workspace_id: str, **kwargs
) -> dict:
    resp = alice_client.post(
        f"/v1/workspaces/{workspace_id}/invitations", json=kwargs or {}
    )
    resp.raise_for_status()
    return resp.json()


@pytest.mark.integration
def test_invitation_happy_path(
    alice, alice_client: httpx.Client, bob, bob_client: httpx.Client
) -> None:
    """Alice creates invite for her workspace; Bob accepts; Bob is now a member."""
    workspace = alice.identity_id

    invitation = _create_invitation(alice_client, workspace, email="bob@example.com")
    token = invitation["token"]
    assert invitation["status"] == "pending"
    assert invitation["workspace_id"] == workspace
    assert invitation["invited_by"] == alice.identity_id
    assert isinstance(token, str) and len(token) > 20

    # Bob isn't a member yet — listing his memberships in Alice's workspace
    # would even fail authz, so just confirm Bob can't read Alice's pending list.
    blocked = bob_client.get(f"/v1/workspaces/{workspace}/invitations")
    assert blocked.status_code == 403, blocked.text

    # Accept as Bob
    accept = bob_client.post("/v1/invitations/accept", json={"token": token})
    assert accept.status_code == 200, accept.text
    payload = accept.json()
    assert payload["workspace_id"] == workspace
    assert payload["user_id"] == bob.identity_id
    assert payload["invitation_id"] == invitation["id"]

    # Now Bob can list members of Alice's workspace (he's a member).
    # A member's email/display_name come from their *identity* (resolved from the
    # caller's own auth context), NOT from the invitation — the invitation email
    # ("bob@example.com" above) is only a delivery hint. So Bob, viewing himself,
    # sees his real identity email.
    members = _members(bob_client, workspace)
    user_ids = {m["user_id"] for m in members}
    assert bob.identity_id in user_ids
    bob_member = next(m for m in members if m["user_id"] == bob.identity_id)
    assert bob_member["email"] == bob.email
    assert bob_member["display_name"] == bob.email

    # Invitation has flipped to accepted
    pending = alice_client.get(
        f"/v1/workspaces/{workspace}/invitations"
    ).raise_for_status().json()
    assert all(i["id"] != invitation["id"] for i in pending), (
        "accepted invitation should not appear in pending list"
    )


@pytest.mark.integration
def test_double_accept_is_idempotent(
    alice, alice_client: httpx.Client, bob, bob_client: httpx.Client
) -> None:
    workspace = alice.identity_id
    token = _create_invitation(alice_client, workspace)["token"]

    first = bob_client.post("/v1/invitations/accept", json={"token": token})
    assert first.status_code == 200
    first_payload = first.json()

    second = bob_client.post("/v1/invitations/accept", json={"token": token})
    assert second.status_code == 200, second.text
    assert second.json() == first_payload, (
        "double-accept should return the exact same membership"
    )


@pytest.mark.integration
def test_consumed_token_rejected_for_other_user(
    alice,
    alice_client: httpx.Client,
    bob,
    bob_client: httpx.Client,
    user_factory,
) -> None:
    """Once Bob accepts, the same token can't be used by Carol."""
    workspace = alice.identity_id
    token = _create_invitation(alice_client, workspace)["token"]

    bob_client.post("/v1/invitations/accept", json={"token": token}).raise_for_status()

    carol = user_factory("carol")
    with httpx.Client(
        base_url=bob_client.base_url,
        headers={"Authorization": f"Bearer {carol.jwt}"},
        timeout=10.0,
    ) as carol_client:
        resp = carol_client.post("/v1/invitations/accept", json={"token": token})
        # Already-accepted invitations 409 for non-original-acceptors.
        assert resp.status_code == 409, resp.text


@pytest.mark.integration
def test_revoked_token_rejected(
    alice, alice_client: httpx.Client, bob_client: httpx.Client
) -> None:
    workspace = alice.identity_id
    invitation = _create_invitation(alice_client, workspace)

    revoke = alice_client.delete(
        f"/v1/workspaces/{workspace}/invitations/{invitation['id']}"
    )
    assert revoke.status_code == 204

    accept = bob_client.post("/v1/invitations/accept", json={"token": invitation["token"]})
    assert accept.status_code == 410, accept.text


@pytest.mark.integration
def test_expired_token_rejected(
    alice, alice_client: httpx.Client, bob_client: httpx.Client
) -> None:
    """Force expiry via psql since we can't fast-forward time in the worker."""
    from tests.e2e.api.conftest import _psql

    workspace = alice.identity_id
    invitation = _create_invitation(alice_client, workspace)

    past = (datetime.utcnow() - timedelta(seconds=10)).isoformat(sep=" ", timespec="seconds")
    _psql(
        f"UPDATE workspace_invitations SET expires_at = '{past}' "
        f"WHERE id = '{invitation['id']}';"
    )

    accept = bob_client.post(
        "/v1/invitations/accept", json={"token": invitation["token"]}
    )
    assert accept.status_code == 410, accept.text


@pytest.mark.integration
def test_invalid_token_404(bob_client: httpx.Client) -> None:
    accept = bob_client.post(
        "/v1/invitations/accept", json={"token": "not-a-real-token-xxx"}
    )
    assert accept.status_code == 404, accept.text


@pytest.mark.integration
def test_cross_workspace_listing_forbidden(
    alice, alice_client: httpx.Client, bob_client: httpx.Client
) -> None:
    """Bob, not a member of Alice's workspace, can't list its invitations or members."""
    workspace = alice.identity_id

    invitations = bob_client.get(f"/v1/workspaces/{workspace}/invitations")
    assert invitations.status_code == 403, invitations.text

    members = bob_client.get(f"/v1/workspaces/{workspace}/members")
    assert members.status_code == 403, members.text
