"""API key CRUD: create -> use -> revoke -> fail."""

from __future__ import annotations

import httpx
import pytest

from tests.e2e.api.conftest import API_URL


@pytest.mark.integration
def test_api_key_create_use_revoke(alice_client: httpx.Client) -> None:
    created = alice_client.post(f"{alice_client.ws}/api-keys/", json={"name": "lifecycle-test"})
    created.raise_for_status()
    body = created.json()
    raw_token = body["token"]
    key_id = body["id"]
    assert body["is_active"] is True
    assert body["token_prefix"] in raw_token

    with httpx.Client(
        base_url=API_URL,
        headers={"Authorization": f"Bearer {raw_token}"},
        timeout=10.0,
    ) as client:
        use = client.get(f"{alice_client.ws}/agents/")
        assert use.status_code == 200, f"API key should work as bearer: {use.text[:200]}"

        listed = client.get(f"{alice_client.ws}/api-keys/")
        assert listed.status_code == 200
        assert any(k["id"] == key_id for k in listed.json())

        revoke = alice_client.delete(f"{alice_client.ws}/api-keys/{key_id}")
        assert revoke.status_code == 204

        post_revoke = client.get(f"{alice_client.ws}/agents/")
        assert post_revoke.status_code == 401, (
            f"Revoked key must return 401, got {post_revoke.status_code}"
        )


@pytest.mark.integration
def test_api_keys_are_workspace_scoped(
    alice_client: httpx.Client, bob_client: httpx.Client
) -> None:
    alice_key_id = (
        alice_client.post(f"{alice_client.ws}/api-keys/", json={"name": "alice-key"})
        .raise_for_status()
        .json()["id"]
    )

    bob_view = bob_client.get(f"{bob_client.ws}/api-keys/")
    bob_view.raise_for_status()
    assert all(k["id"] != alice_key_id for k in bob_view.json()), (
        "Bob must not see Alice's API keys"
    )

    bob_direct = bob_client.get(f"{bob_client.ws}/api-keys/{alice_key_id}")
    assert bob_direct.status_code == 404
