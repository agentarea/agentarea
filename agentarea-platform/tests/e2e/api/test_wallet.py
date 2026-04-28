"""Agent wallet HTTP API end-to-end tests."""

from __future__ import annotations

import httpx
import pytest


def _create_agent(client: httpx.Client, name: str = "wallet-host") -> str:
    resp = client.post(
        "/v1/agents/",
        json={
            "name": name,
            "description": "for wallet e2e",
            "instruction": "respond",
            "model_id": "gpt-4",
            "agent_type": "stateless",
        },
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _wallet_payload(*, budget: float = 12.5) -> dict:
    return {
        "wallet_type": "mpp",
        "mpp_config": {
            "payment_method_types": ["charge"],
            "session_budget_usd": budget,
        },
        "service_budget_usd": budget,
        "service_budget_period": "daily",
    }


@pytest.mark.integration
def test_wallet_lifecycle(alice_client: httpx.Client) -> None:
    agent_id = _create_agent(alice_client)

    created = alice_client.post(f"/v1/agents/{agent_id}/wallet", json=_wallet_payload())
    assert created.status_code == 201, created.text[:200]
    wallet_id = created.json()["id"]
    assert created.json()["wallet_type"] == "mpp"
    assert created.json()["service_budget_usd"] == 12.5

    duplicate = alice_client.post(f"/v1/agents/{agent_id}/wallet", json=_wallet_payload())
    assert duplicate.status_code == 409

    fetched = alice_client.get(f"/v1/agents/{agent_id}/wallet")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == wallet_id

    balance = alice_client.get(f"/v1/agents/{agent_id}/wallet/balance")
    assert balance.status_code == 200
    assert balance.json()["remaining"] == 12.5

    payments = alice_client.get(f"/v1/agents/{agent_id}/wallet/payments")
    assert payments.status_code == 200
    assert payments.json()["items"] == []

    funded = alice_client.post(
        f"/v1/agents/{agent_id}/wallet/fund",
        json={"service_budget_usd": 25.0},
    )
    assert funded.status_code == 200
    assert funded.json()["service_budget_usd"] == 25.0

    updated = alice_client.put(
        f"/v1/agents/{agent_id}/wallet",
        json={"service_budget_period": "monthly", "status": "disabled"},
    )
    assert updated.status_code == 200
    assert updated.json()["service_budget_period"] == "monthly"
    assert updated.json()["status"] == "disabled"

    deleted = alice_client.delete(f"/v1/agents/{agent_id}/wallet")
    assert deleted.status_code == 204

    gone = alice_client.get(f"/v1/agents/{agent_id}/wallet")
    assert gone.status_code == 404


@pytest.mark.integration
def test_wallet_is_workspace_scoped(
    alice_client: httpx.Client, bob_client: httpx.Client
) -> None:
    alice_agent_id = _create_agent(alice_client, "alice-wallet-host")

    alice_client.post(
        f"/v1/agents/{alice_agent_id}/wallet", json=_wallet_payload()
    ).raise_for_status()

    bob_get = bob_client.get(f"/v1/agents/{alice_agent_id}/wallet")
    assert bob_get.status_code == 404

    bob_create = bob_client.post(
        f"/v1/agents/{alice_agent_id}/wallet", json=_wallet_payload()
    )
    assert bob_create.status_code == 404

