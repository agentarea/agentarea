"""Auth hardening: malformed tokens, signature tampering, workspace selection.

These are regression tests for the most common auth-layer mistakes. Any
failure here is a critical bug — the whole workspace isolation model depends
on these invariants holding.
"""

from __future__ import annotations

import base64

import httpx
import pytest

from tests.e2e.api.conftest import AuthedUser, WorkspaceClient


def _tamper_signature(jwt: str) -> str:
    header, payload, sig = jwt.split(".")
    decoded = base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
    flipped = bytes([decoded[0] ^ 0xFF]) + decoded[1:]
    new_sig = base64.urlsafe_b64encode(flipped).rstrip(b"=").decode()
    return f"{header}.{payload}.{new_sig}"


def _tamper_payload(jwt: str, attacker_sub: str) -> str:
    """Alter `sub` in payload; signature becomes invalid — verify server catches it."""
    import json

    header, payload, sig = jwt.split(".")
    decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    body = json.loads(decoded)
    body["sub"] = attacker_sub
    new_payload = base64.urlsafe_b64encode(
        json.dumps(body, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()
    return f"{header}.{new_payload}.{sig}"


@pytest.mark.integration
def test_malformed_jwt_rejected(anon_client: httpx.Client) -> None:
    resp = anon_client.get(
        "/v1/workspaces/any-workspace/agents/", headers={"Authorization": "Bearer not.a.jwt"}
    )
    assert resp.status_code == 401


@pytest.mark.integration
def test_tampered_signature_rejected(alice: AuthedUser, anon_client: httpx.Client) -> None:
    bad = _tamper_signature(alice.jwt)
    resp = anon_client.get("/v1/workspaces/any-workspace/agents/", headers={"Authorization": f"Bearer {bad}"})
    assert resp.status_code == 401, (
        f"Tampered signature must be rejected; got {resp.status_code}: {resp.text[:200]}"
    )


@pytest.mark.integration
def test_tampered_payload_rejected(
    alice: AuthedUser, bob: AuthedUser, anon_client: httpx.Client
) -> None:
    """Swap `sub` in Alice's JWT to Bob's id; signature is broken → must 401."""
    bad = _tamper_payload(alice.jwt, attacker_sub=bob.identity_id)
    resp = anon_client.get("/v1/workspaces/any-workspace/agents/", headers={"Authorization": f"Bearer {bad}"})
    assert resp.status_code == 401


@pytest.mark.integration
def test_a_workspace_header_selects_nothing(
    alice_client: WorkspaceClient,
    bob: AuthedUser,
    bob_client: WorkspaceClient,
) -> None:
    """Alice's JWT on her own workspace path + Bob's workspace in the retired headers.

    The path is the only selector: the headers are ignored, the request acts in
    Alice's workspace, and Bob's data stays invisible to her.
    """
    bob_project = bob_client.post(
        f"{bob_client.ws}/projects/", json={"name": "bob-secret"}
    ).raise_for_status().json()

    attack = alice_client.get(
        f"{alice_client.ws}/projects/",
        headers={
            "X-AgentArea-Workspace": bob_client.ws.rsplit("/", 1)[1],
            "X-Workspace-ID": bob.identity_id,
            "X-Workspace-Slug": bob_client.ws.rsplit("/", 1)[1],
        },
    )
    assert attack.status_code == 200
    items = attack.json()
    items = items if isinstance(items, list) else items.get("items", [])
    ids = {p["id"] for p in items}
    assert bob_project["id"] not in ids, (
        "CRITICAL: Alice read Bob's project by naming his workspace in a header"
    )


@pytest.mark.integration
def test_foreign_workspace_path_is_forbidden(
    alice_client: WorkspaceClient,
    bob_client: WorkspaceClient,
) -> None:
    bob_project_id = bob_client.post(
        f"{bob_client.ws}/projects/", json={"name": "bob-direct"}
    ).raise_for_status().json()["id"]

    attack = alice_client.get(f"{bob_client.ws}/projects/{bob_project_id}")
    assert attack.status_code == 403, (
        f"CRITICAL: Alice reached Bob's workspace by naming it in the path: "
        f"{attack.status_code} {attack.text[:200]}"
    )


@pytest.mark.integration
def test_unknown_workspace_path_is_refused_like_a_foreign_one(
    alice_client: WorkspaceClient,
    bob_client: WorkspaceClient,
) -> None:
    foreign = alice_client.get(f"{bob_client.ws}/projects/")
    unknown = alice_client.get("/v1/workspaces/no-such-workspace-e2e/projects/")

    assert foreign.status_code == unknown.status_code == 403
    assert foreign.json()["detail"] == unknown.json()["detail"]


@pytest.mark.integration
def test_api_key_cannot_leave_its_workspace(
    alice_client: WorkspaceClient,
    bob_client: WorkspaceClient,
) -> None:
    """An API key acts only in the workspace it was issued for, even one its
    owner could otherwise reach — and never in a workspace the owner cannot."""
    raw = alice_client.post(f"{alice_client.ws}/api-keys/", json={"name": "spoof-test"})
    raw.raise_for_status()
    alice_key = raw.json()["token"]

    with httpx.Client(
        base_url=alice_client.base_url,
        headers={"Authorization": f"Bearer {alice_key}"},
        timeout=10.0,
    ) as key_client:
        own = key_client.get(f"{alice_client.ws}/projects/")
        foreign = key_client.get(f"{bob_client.ws}/projects/")

    assert own.status_code == 200, own.text[:200]
    assert foreign.status_code == 403, (
        f"CRITICAL: Alice's API key reached Bob's workspace: "
        f"{foreign.status_code} {foreign.text[:200]}"
    )
