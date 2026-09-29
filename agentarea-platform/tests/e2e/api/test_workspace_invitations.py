"""End-to-end tests for workspace invitation flow.

Covers:
  1. happy path — Alice creates invite, Bob accepts, membership exists
  2. consumed token — second accept of same token fails (or is idempotent
     when Bob accepts twice)
  3. expired token — accept after expiry fails 410
  4. revoked token — accept after revoke fails 410
  5. cross-workspace listing blocked — Bob can't list Alice's invitations
  6. double-accept idempotent — Bob accepting twice returns same membership
  7. emailed invitation — only the addressed account can preview or accept it
"""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest


def _members(client: httpx.Client, workspace_path: str) -> list[dict]:
    resp = client.get(f"{workspace_path}/members")
    resp.raise_for_status()
    return resp.json()


def _create_invitation(
    alice_client: httpx.Client, workspace_path: str, **kwargs
) -> dict:
    resp = alice_client.post(f"{workspace_path}/invitations", json=kwargs or {})
    resp.raise_for_status()
    return resp.json()


@pytest.mark.integration
def test_invitation_happy_path(
    alice, alice_client: httpx.Client, bob, bob_client: httpx.Client
) -> None:
    """Alice creates invite for her workspace; Bob accepts; Bob is now a member."""
    workspace = alice.identity_id
    workspace_path = alice_client.ws

    invitation = _create_invitation(alice_client, workspace_path, email=bob.email.upper())
    token = invitation["token"]
    assert invitation["status"] == "pending"
    assert invitation["workspace_id"] == workspace
    assert invitation["invited_by"] == alice.identity_id
    assert isinstance(token, str) and len(token) > 20

    # Bob isn't a member yet — listing his memberships in Alice's workspace
    # would even fail authz, so just confirm Bob can't read Alice's pending list.
    blocked = bob_client.get(f"{workspace_path}/invitations")
    assert blocked.status_code == 403, blocked.text

    # Accept as Bob
    accept = bob_client.post("/v1/invitations/accept", json={"token": token})
    assert accept.status_code == 200, accept.text
    payload = accept.json()
    assert payload["workspace_id"] == workspace
    assert payload["user_id"] == bob.identity_id
    assert payload["invitation_id"] == invitation["id"]

    # Now Bob can list members of Alice's workspace (he's a member).
    # A member's email/display_name come from their *identity*, resolved through
    # the identity provider, NOT from the invitation — the invitation email
    # (upper-cased above) only says who may redeem the link.
    members = _members(bob_client, workspace_path)
    user_ids = {m["user_id"] for m in members}
    assert bob.identity_id in user_ids
    bob_member = next(m for m in members if m["user_id"] == bob.identity_id)
    assert bob_member["email"] == bob.email
    assert bob_member["display_name"] == bob.email

    # Alice sees the same identity for Bob — resolution is not limited to the
    # caller looking at themselves, which is what made this list read as a
    # column of raw uuids.
    as_alice = _members(alice_client, workspace_path)
    bob_as_alice_sees_him = next(m for m in as_alice if m["user_id"] == bob.identity_id)
    assert bob_as_alice_sees_him["email"] == bob.email

    # Alice provisioned the workspace, so she owns it and Bob does not.
    alice_member = next(m for m in as_alice if m["user_id"] == alice.identity_id)
    assert alice_member["is_owner"] is True
    assert bob_as_alice_sees_him["is_owner"] is False

    # joined_at is a recorded fact, not a stamp applied at read time.
    assert bob_as_alice_sees_him["joined_at"] is not None
    assert _members(alice_client, workspace_path) == as_alice

    # Invitation has flipped to accepted
    pending = alice_client.get(
        f"{workspace_path}/invitations"
    ).raise_for_status().json()
    assert all(i["id"] != invitation["id"] for i in pending), (
        "accepted invitation should not appear in pending list"
    )


@pytest.mark.integration
def test_emailed_invitation_is_only_for_its_addressee(
    alice, alice_client: httpx.Client, bob, bob_client: httpx.Client, user_factory
) -> None:
    workspace_path = alice_client.ws
    token = _create_invitation(alice_client, workspace_path, email=bob.email)["token"]

    carol = user_factory("carol")
    with httpx.Client(
        base_url=bob_client.base_url,
        headers={"Authorization": f"Bearer {carol.jwt}"},
        timeout=10.0,
    ) as carol_client:
        preview = carol_client.post("/v1/invitations/preview", json={"token": token})
        assert preview.status_code == 403, preview.text
        accept = carol_client.post("/v1/invitations/accept", json={"token": token})
        assert accept.status_code == 403, accept.text

    preview = bob_client.post("/v1/invitations/preview", json={"token": token})
    assert preview.status_code == 200, preview.text
    assert set(preview.json()) == {
        "workspace_name",
        "inviter_display_name",
        "inviter_email",
        "expires_at",
    }
    assert preview.json()["inviter_email"] == alice.email

    accept = bob_client.post("/v1/invitations/accept", json={"token": token})
    assert accept.status_code == 200, accept.text


@pytest.mark.integration
def test_double_accept_is_idempotent(
    alice, alice_client: httpx.Client, bob, bob_client: httpx.Client
) -> None:
    workspace_path = alice_client.ws
    token = _create_invitation(alice_client, workspace_path)["token"]

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
    workspace_path = alice_client.ws
    token = _create_invitation(alice_client, workspace_path)["token"]

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
    workspace_path = alice_client.ws
    invitation = _create_invitation(alice_client, workspace_path)

    revoke = alice_client.delete(
        f"{workspace_path}/invitations/{invitation['id']}"
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

    workspace_path = alice_client.ws
    invitation = _create_invitation(alice_client, workspace_path)

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


def _join(alice_client: httpx.Client, workspace_path: str, client: httpx.Client) -> None:
    token = _create_invitation(alice_client, workspace_path)["token"]
    client.post("/v1/invitations/accept", json={"token": token}).raise_for_status()


@pytest.mark.integration
def test_owner_cannot_be_removed(alice, alice_client: httpx.Client) -> None:
    """The owner keeps access until ownership moves; otherwise the workspace strands."""
    workspace = alice.identity_id
    workspace_path = alice_client.ws
    _members(alice_client, workspace_path)  # provisions the owner's membership

    removed = alice_client.delete(
        f"{workspace_path}/members/{alice.identity_id}"
    )
    assert removed.status_code == 409, removed.text

    user_ids = {m["user_id"] for m in _members(alice_client, workspace_path)}
    assert alice.identity_id in user_ids


@pytest.mark.integration
def test_non_owner_cannot_remove_another_member(
    alice, alice_client: httpx.Client, bob, bob_client: httpx.Client, user_factory
) -> None:
    workspace_path = alice_client.ws
    _join(alice_client, workspace_path, bob_client)

    carol = user_factory("carol")
    with httpx.Client(
        base_url=bob_client.base_url,
        headers={"Authorization": f"Bearer {carol.jwt}"},
        timeout=10.0,
    ) as carol_client:
        _join(alice_client, workspace_path, carol_client)

        refused = bob_client.delete(
            f"{workspace_path}/members/{carol.identity_id}"
        )
        assert refused.status_code == 403, refused.text

        still_there = {m["user_id"] for m in _members(carol_client, workspace_path)}
        assert carol.identity_id in still_there


@pytest.mark.integration
def test_member_can_leave_and_the_owner_can_remove(
    alice, alice_client: httpx.Client, bob, bob_client: httpx.Client, user_factory
) -> None:
    workspace_path = alice_client.ws
    _join(alice_client, workspace_path, bob_client)

    left = bob_client.delete(f"{workspace_path}/members/{bob.identity_id}")
    assert left.status_code == 204, left.text
    assert bob.identity_id not in {
        m["user_id"] for m in _members(alice_client, workspace_path)
    }

    carol = user_factory("carol")
    with httpx.Client(
        base_url=bob_client.base_url,
        headers={"Authorization": f"Bearer {carol.jwt}"},
        timeout=10.0,
    ) as carol_client:
        _join(alice_client, workspace_path, carol_client)

        removed = alice_client.delete(
            f"{workspace_path}/members/{carol.identity_id}"
        )
        assert removed.status_code == 204, removed.text
        assert carol.identity_id not in {
            m["user_id"] for m in _members(alice_client, workspace_path)
        }


@pytest.mark.integration
def test_cross_workspace_listing_forbidden(
    alice, alice_client: httpx.Client, bob_client: httpx.Client
) -> None:
    """Bob, not a member of Alice's workspace, can't list its invitations or members."""
    workspace = alice.identity_id
    workspace_path = alice_client.ws

    invitations = bob_client.get(f"{workspace_path}/invitations")
    assert invitations.status_code == 403, invitations.text

    members = bob_client.get(f"{workspace_path}/members")
    assert members.status_code == 403, members.text
