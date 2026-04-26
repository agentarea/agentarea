"""Auth hardening: malformed tokens, signature tampering, workspace spoofing.

These are regression tests for the most common auth-layer mistakes. Any
failure here is a critical bug — the whole workspace isolation model depends
on these invariants holding.
"""

from __future__ import annotations

import base64

import httpx
import pytest

from tests.e2e.api.conftest import AuthedUser


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
        "/v1/agents/", headers={"Authorization": "Bearer not.a.jwt"}
    )
    assert resp.status_code == 401


@pytest.mark.integration
def test_tampered_signature_rejected(alice: AuthedUser, anon_client: httpx.Client) -> None:
    bad = _tamper_signature(alice.jwt)
    resp = anon_client.get("/v1/agents/", headers={"Authorization": f"Bearer {bad}"})
    assert resp.status_code == 401, (
        f"Tampered signature must be rejected; got {resp.status_code}: {resp.text[:200]}"
    )


@pytest.mark.integration
def test_tampered_payload_rejected(
    alice: AuthedUser, bob: AuthedUser, anon_client: httpx.Client
) -> None:
    """Swap `sub` in Alice's JWT to Bob's id; signature is broken → must 401."""
    bad = _tamper_payload(alice.jwt, attacker_sub=bob.identity_id)
    resp = anon_client.get("/v1/agents/", headers={"Authorization": f"Bearer {bad}"})
    assert resp.status_code == 401


@pytest.mark.integration
def test_workspace_id_spoof_cannot_read_other_users_data(
    alice_client: httpx.Client,
    bob: AuthedUser,
    bob_client: httpx.Client,
) -> None:
    """Alice's JWT + Bob's workspace_id in X-Workspace-ID header.

    The server must NOT return Bob's resources. Either it rejects (403) or it
    silently scopes to Alice's real workspace — in both cases Bob's data must
    stay invisible to Alice.
    """
    bob_project = bob_client.post(
        "/v1/projects/", json={"name": "bob-secret"}
    ).raise_for_status().json()

    attack = alice_client.get(
        "/v1/projects/",
        headers={"X-Workspace-ID": bob.identity_id},
    )
    assert attack.status_code < 500
    items = attack.json()
    items = items if isinstance(items, list) else items.get("items", [])
    ids = {p["id"] for p in items}
    assert bob_project["id"] not in ids, (
        "CRITICAL: Alice read Bob's project by spoofing X-Workspace-ID header"
    )


@pytest.mark.integration
def test_workspace_id_spoof_cannot_read_bob_project_by_id(
    alice_client: httpx.Client,
    bob: AuthedUser,
    bob_client: httpx.Client,
) -> None:
    bob_project_id = bob_client.post(
        "/v1/projects/", json={"name": "bob-direct"}
    ).raise_for_status().json()["id"]

    attack = alice_client.get(
        f"/v1/projects/{bob_project_id}",
        headers={"X-Workspace-ID": bob.identity_id},
    )
    assert attack.status_code in (403, 404), (
        f"CRITICAL: Alice fetched Bob's project via X-Workspace-ID spoof: "
        f"{attack.status_code} {attack.text[:200]}"
    )


@pytest.mark.integration
def test_api_key_workspace_id_spoof_blocked(
    alice_client: httpx.Client,
    bob: AuthedUser,
    bob_client: httpx.Client,
) -> None:
    """API key + X-Workspace-ID is a documented override path; make sure it
    cannot be used to reach a workspace the key owner does not belong to."""
    bob_project_id = bob_client.post(
        "/v1/projects/", json={"name": "bob-for-api-key"}
    ).raise_for_status().json()["id"]

    raw = alice_client.post("/v1/api-keys/", json={"name": "spoof-test"})
    raw.raise_for_status()
    alice_key = raw.json()["token"]

    with httpx.Client(
        base_url=alice_client.base_url,
        headers={
            "Authorization": f"Bearer {alice_key}",
            "X-Workspace-ID": bob.identity_id,
        },
        timeout=10.0,
    ) as attacker:
        resp = attacker.get(f"/v1/projects/{bob_project_id}")
        assert resp.status_code in (403, 404), (
            f"CRITICAL: Alice's API key + Bob's workspace header reached Bob's data: "
            f"{resp.status_code} {resp.text[:200]}"
        )
